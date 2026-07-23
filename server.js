const express = require('express');
const http = require('http');
const WebSocket = require('ws');
const os = require('os');
const { spawn, exec } = require('child_process');
const path = require('path');

const PORT = process.env.PORT || 3030;
const app = express();
const server = http.createServer(app);
const wss = new WebSocket.Server({ server });

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// Store active GST child process if launched via GUI
let activeGstProcess = null;
let streamStats = {
  activeClients: 0,
  packetsSent: 0,
  bytesSent: 0,
  startTime: null,
  isBroadcasting: false,
  streamConfig: {
    multicastHost: '224.0.0.1',
    port: 5004,
    frameSize: 10,
    bitrate: 160000,
    platform: os.platform()
  }
};

// Helper: Get local network IPv4 addresses
function getLocalIpAddresses() {
  const interfaces = os.networkInterfaces();
  const addresses = [];
  for (const name of Object.keys(interfaces)) {
    for (const iface of interfaces[name]) {
      // Ignore IPv6 and internal loopback (127.0.0.1)
      if (iface.family === 'IPv4' && !iface.internal) {
        addresses.push({ interface: name, address: iface.address });
      }
    }
  }
  return addresses;
}

// REST Endpoints
app.get('/api/info', (req, res) => {
  res.json({
    platform: os.platform(),
    hostname: os.hostname(),
    localIps: getLocalIpAddresses(),
    port: PORT,
    stats: streamStats
  });
});

app.get('/api/gstreamer-commands', (req, res) => {
  const host = req.query.host || '224.0.0.1';
  const port = req.query.port || 5004;
  const frameSize = req.query.frameSize || 10;
  const bitrate = req.query.bitrate || 160000;
  const jitter = req.query.jitter || 10;

  const commands = {
    windows: {
      server: `gst-launch-1.0 -v wasapisrc loopback=true ! audioconvert ! audioresample ! audio/x-raw,rate=48000,channels=2 ! opusenc frame-size=${frameSize} bitrate=${bitrate} ! rtpopuspay ! udpsink host=${host} port=${port} auto-multicast=true`,
      client: `gst-launch-1.0 -v udpsrc multicast-group=${host} port=${port} caps="application/x-rtp,media=audio,clock-rate=48000,encoding-name=OPUS" ! rtpjitterbuffer latency=${jitter} ! rtpopusdepay ! opusdec ! audioconvert ! audioresample ! autoaudiosink`
    },
    linux: {
      server: `gst-launch-1.0 -v pulsesrc device="<MONITOR_DEVICE>" ! audioconvert ! audioresample ! audio/x-raw,rate=48000,channels=2,format=S16LE ! opusenc frame-size=${frameSize} bitrate=${bitrate} ! rtpopuspay ! udpsink host=${host} port=${port} auto-multicast=true`,
      client: `gst-launch-1.0 -v udpsrc multicast-group=${host} port=${port} caps="application/x-rtp,media=audio,clock-rate=48000,encoding-name=OPUS" ! rtpjitterbuffer latency=${jitter} ! rtpopusdepay ! opusdec ! audioconvert ! audioresample ! autoaudiosink`
    },
    macOS: {
      server: `gst-launch-1.0 -v osxaudiosrc device="<BLACKHOLE_DEVICE>" ! audioconvert ! audioresample ! audio/x-raw,rate=48000,channels=2 ! opusenc frame-size=${frameSize} bitrate=${bitrate} ! rtpopuspay ! udpsink host=${host} port=${port} auto-multicast=true`,
      client: `gst-launch-1.0 -v udpsrc multicast-group=${host} port=${port} caps="application/x-rtp,media=audio,clock-rate=48000,encoding-name=OPUS" ! rtpjitterbuffer latency=${jitter} ! rtpopusdepay ! opusdec ! audioconvert ! audioresample ! autoaudiosink`
    }
  };

  res.json(commands);
});

// Start/Stop GStreamer Server process via backend (Optional feature)
app.post('/api/gstreamer/start', (req, res) => {
  const { command } = req.body;
  if (!command) return res.status(400).json({ error: 'Command missing' });

  if (activeGstProcess) {
    return res.status(400).json({ error: 'GStreamer process already running' });
  }

  try {
    const parts = command.trim().split(/\s+/);
    const cmd = parts[0];
    const args = parts.slice(1);

    activeGstProcess = spawn(cmd, args, { shell: true });
    streamStats.isBroadcasting = true;
    streamStats.startTime = Date.now();

    activeGstProcess.on('error', (err) => {
      console.error('GStreamer execution error:', err);
      streamStats.isBroadcasting = false;
      activeGstProcess = null;
    });

    activeGstProcess.on('exit', (code) => {
      console.log(`GStreamer process exited with code ${code}`);
      streamStats.isBroadcasting = false;
      activeGstProcess = null;
    });

    res.json({ success: true, message: 'GStreamer pipeline started successfully.' });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.post('/api/gstreamer/stop', (req, res) => {
  if (activeGstProcess) {
    activeGstProcess.kill('SIGTERM');
    activeGstProcess = null;
    streamStats.isBroadcasting = false;
    return res.json({ success: true, message: 'GStreamer process terminated.' });
  }
  res.json({ success: true, message: 'No process was running.' });
});

// WebSocket low-latency audio broadcasting & client synchronization
wss.on('connection', (ws, req) => {
  streamStats.activeClients++;
  broadcastStats();

  ws.on('message', (message, isBinary) => {
    if (isBinary) {
      // Audio packet relay to all listening web clients
      streamStats.packetsSent++;
      streamStats.bytesSent += message.length;
      wss.clients.forEach((client) => {
        if (client !== ws && client.readyState === WebSocket.OPEN) {
          client.send(message, { binary: true });
        }
      });
    } else {
      try {
        const data = JSON.parse(message.toString());
        if (data.type === 'ping') {
          ws.send(JSON.stringify({ type: 'pong', timestamp: data.timestamp, serverTime: Date.now() }));
        } else if (data.type === 'config_update') {
          streamStats.streamConfig = { ...streamStats.streamConfig, ...data.config };
          broadcastStats();
        }
      } catch (e) {
        // Invalid JSON or simple text
      }
    }
  });

  ws.on('close', () => {
    streamStats.activeClients = Math.max(0, streamStats.activeClients - 1);
    broadcastStats();
  });
});

function broadcastStats() {
  const payload = JSON.stringify({ type: 'stats_update', stats: streamStats });
  wss.clients.forEach((client) => {
    if (client.readyState === WebSocket.OPEN) {
      client.send(payload);
    }
  });
}

let currentPort = parseInt(process.env.PORT || 3030);

function startServer(portToTry) {
  server.removeAllListeners('error');
  server.on('error', (err) => {
    if (err.code === 'EADDRINUSE') {
      console.log(`Port ${portToTry} in use, trying port ${portToTry + 1}...`);
      startServer(portToTry + 1);
    } else {
      console.error('Server error:', err);
    }
  });

  server.listen(portToTry, () => {
    console.log(`====================================================`);
    console.log(` Wi-Lo-St Audio Streaming Server running on port ${portToTry}`);
    console.log(` Local Network Access URLs:`);
    getLocalIpAddresses().forEach(ip => {
      console.log(`   http://${ip.address}:${portToTry}`);
    });
    console.log(`====================================================`);
  });
}

startServer(currentPort);


