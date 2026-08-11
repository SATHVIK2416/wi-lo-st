const express = require('express');
const http = require('http');
const https = require('https');
const WebSocket = require('ws');
const os = require('os');
const path = require('path');
const selfsigned = require('selfsigned');
const { spawn } = require('child_process');

const PORT_HTTP = parseInt(process.env.PORT || 3000);
const PORT_HTTPS = parseInt(process.env.HTTPS_PORT || 3443);

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// Generate dynamic SSL cert for HTTPS Secure Context on LAN
const pems = selfsigned.generate([{ name: 'commonName', value: 'wi-lo-st.local' }], { days: 365 });
const sslOptions = { key: pems.private, cert: pems.cert };

const httpServer = http.createServer(app);
const httpsServer = https.createServer(sslOptions, app);

// Attach WebSocket servers to both HTTP and HTTPS
const wssHttp = new WebSocket.Server({ server: httpServer });
const wssHttps = new WebSocket.Server({ server: httpsServer });

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

function getLocalIpAddresses() {
  const interfaces = os.networkInterfaces();
  const addresses = [];
  for (const name of Object.keys(interfaces)) {
    for (const iface of interfaces[name]) {
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
    portHttp: PORT_HTTP,
    portHttps: PORT_HTTPS,
    stats: streamStats
  });
});

app.get('/api/gstreamer-commands', (req, res) => {
  const host = req.query.host || '224.0.0.1';
  const port = req.query.port || 5004;
  const frameSize = req.query.frameSize || 10;
  const bitrate = req.query.bitrate || 160000;

  const commands = {
    windows: {
      server: `gst-launch-1.0 -v wasapisrc loopback=true ! audioconvert ! audioresample ! audio/x-raw,rate=48000,channels=2 ! opusenc frame-size=${frameSize} bitrate=${bitrate} music-mode=true ! rtpopuspay ! udpsink host=${host} port=${port} auto-multicast=true`,
      client: `gst-launch-1.0 -v udpsrc multicast-group=${host} port=${port} caps="application/x-rtp,media=audio,clock-rate=48000,encoding-name=OPUS" ! rtpjitterbuffer latency=500 ! rtpopusdepay ! opusdec ! audioconvert ! autoaudiosink`
    },
    linux: {
      server: `gst-launch-1.0 -v pulsesrc device="<MONITOR_DEVICE>" ! audioconvert ! audioresample ! audio/x-raw,rate=48000,channels=2,format=S16LE ! opusenc frame-size=${frameSize} bitrate=${bitrate} music-mode=true ! rtpopuspay ! udpsink host=${host} port=${port} auto-multicast=true`,
      client: `gst-launch-1.0 -v udpsrc multicast-group=${host} port=${port} caps="application/x-rtp,media=audio,clock-rate=48000,encoding-name=OPUS" ! rtpjitterbuffer latency=500 ! rtpopusdepay ! opusdec ! audioconvert ! autoaudiosink`
    },
    macOS: {
      server: `gst-launch-1.0 -v osxaudiosrc device="<BLACKHOLE_DEVICE>" ! audioconvert ! audioresample ! audio/x-raw,rate=48000,channels=2 ! opusenc frame-size=${frameSize} bitrate=${bitrate} music-mode=true ! rtpopuspay ! udpsink host=${host} port=${port} auto-multicast=true`,
      client: `gst-launch-1.0 -v udpsrc multicast-group=${host} port=${port} caps="application/x-rtp,media=audio,clock-rate=48000,encoding-name=OPUS" ! rtpjitterbuffer latency=500 ! rtpopusdepay ! opusdec ! audioconvert ! autoaudiosink`
    }
  };

  res.json(commands);
});

function createAndStartServer(basePort, isHttps = false) {
  let portToTry = basePort;
  const srv = isHttps 
    ? https.createServer(sslOptions, app) 
    : http.createServer(app);
  
  const wss = new WebSocket.Server({ server: srv });

  wss.on('connection', (ws) => {
    streamStats.activeClients++;
    broadcastStats();

    ws.on('message', (message, isBinary) => {
      if (isBinary) {
        streamStats.packetsSent++;
        streamStats.bytesSent += message.length;
        activeWssList.forEach(activeWss => {
          activeWss.clients.forEach((client) => {
            if (client !== ws && client.readyState === WebSocket.OPEN) {
              client.send(message, { binary: true });
            }
          });
        });
      } else {
        try {
          const data = JSON.parse(message.toString());
          if (data.type === 'ping') {
            ws.send(JSON.stringify({ type: 'pong', timestamp: data.timestamp, serverTime: Date.now() }));
          }
        } catch (e) {}
      }
    });

    ws.on('close', () => {
      streamStats.activeClients = Math.max(0, streamStats.activeClients - 1);
      broadcastStats();
    });
  });

  activeWssList.push(wss);

  srv.on('error', (err) => {
    if (err.code === 'EADDRINUSE') {
      console.log(`Port ${portToTry} in use, trying ${portToTry + 1}...`);
      createAndStartServer(portToTry + 1, isHttps);
    } else {
      console.error('Server error:', err);
    }
  });

  wss.on('error', (err) => {
    // Prevent unhandled wss error crashes when port is in use
  });

  srv.listen(portToTry, () => {
    const proto = isHttps ? 'HTTPS' : 'HTTP';
    const scheme = isHttps ? 'https' : 'http';
    console.log(`====================================================`);
    console.log(` Wi-Lo-St Server running on ${proto} port ${portToTry}`);
    console.log(` Access URLs:`);
    console.log(`   ${scheme}://localhost:${portToTry}`);
    getLocalIpAddresses().forEach(ip => {
      console.log(`   ${scheme}://${ip.address}:${portToTry}`);
    });
    console.log(`====================================================`);
  });
}

const activeWssList = [];

function broadcastStats() {
  const payload = JSON.stringify({ type: 'stats_update', stats: streamStats });
  activeWssList.forEach(wss => {
    wss.clients.forEach((client) => {
      if (client.readyState === WebSocket.OPEN) {
        client.send(payload);
      }
    });
  });
}

createAndStartServer(PORT_HTTP, false);
createAndStartServer(PORT_HTTPS, true);




