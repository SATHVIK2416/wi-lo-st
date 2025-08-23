// WebRTC signaling + static file host for low-latency system audio broadcast
const express = require('express');
const path = require('path');
const http = require('http');
const { Server } = require('socket.io');
const os = require('os');

const app = express();
const server = http.createServer(app);
const io = new Server(server, { cors: { origin: '*' } });
const PORT = process.env.PORT || 3000;

app.use(express.static(path.join(__dirname, 'public')));

let hostSocketId = null;              // current broadcaster socket id
const viewers = new Map();            // viewerId -> { createdAt }

io.on('connection', socket => {
  console.log('🔌 connect', socket.id);

  socket.on('register-host', () => {
    hostSocketId = socket.id;
    console.log('🎙️ host', socket.id);
    socket.emit('host-confirmed');
    broadcastStats();
  });

  socket.on('announce-streaming', () => {
    if (socket.id !== hostSocketId) return;
    viewers.forEach((_, vid) => io.to(hostSocketId).emit('viewer-joined', { viewerId: vid }));
    io.emit('host-streaming');
  });

  socket.on('viewer-join', () => {
    if (!hostSocketId) return socket.emit('no-host');
    viewers.set(socket.id, { createdAt: Date.now() });
    io.to(hostSocketId).emit('viewer-joined', { viewerId: socket.id });
    broadcastStats();
  });

  socket.on('webrtc-offer', ({ viewerId, sdp }) => {
    io.to(viewerId).emit('webrtc-offer', { sdp, hostId: socket.id });
  });

  socket.on('webrtc-answer', ({ hostId, sdp }) => {
    io.to(hostId).emit('webrtc-answer', { sdp, viewerId: socket.id });
  });

  socket.on('webrtc-ice-candidate', ({ targetId, candidate }) => {
    if (targetId) io.to(targetId).emit('webrtc-ice-candidate', { candidate, from: socket.id });
  });

  // Listener periodically reports quality stats -> forward to host
  socket.on('listener-stats', payload => {
    if (hostSocketId) io.to(hostSocketId).emit('listener-stats', { viewerId: socket.id, ...payload });
  });

  socket.on('disconnect-viewer', ({ viewerId }) => {
    if (viewers.has(viewerId)) io.to(viewerId).emit('disconnect-request');
  });

  socket.on('disconnect', () => {
    if (socket.id === hostSocketId) {
      hostSocketId = null;
      viewers.forEach((_, vid) => io.to(vid).emit('host-left'));
      viewers.clear();
      broadcastStats();
    } else if (viewers.has(socket.id)) {
      viewers.delete(socket.id);
      if (hostSocketId) io.to(hostSocketId).emit('viewer-left', { viewerId: socket.id });
      broadcastStats();
    }
    console.log('🔌 disconnect', socket.id);
  });
});

function broadcastStats() {
  io.emit('stats', {
    viewerCount: viewers.size,
    hostPresent: !!hostSocketId,
    viewerIds: Array.from(viewers.keys())
  });
}

app.get('/network-info', (_req, res) => {
  const interfaces = os.networkInterfaces();
  const addresses = [];
  for (const name in interfaces) {
    for (const net of interfaces[name]) {
      if (net.family === 'IPv4' && !net.internal) {
        addresses.push({ interface: name, address: net.address, url: `http://${net.address}:${PORT}` });
      }
    }
  }
  res.json({ addresses, localUrl: `http://localhost:${PORT}` });
});

app.get('/stats', (_req, res) => {
  res.json({ viewerCount: viewers.size, hostPresent: !!hostSocketId });
});

app.get('/', (_req, res) => res.sendFile(path.join(__dirname, 'public', 'index.html')));
app.get('/listen', (_req, res) => res.sendFile(path.join(__dirname, 'public', 'listen.html')));

server.listen(PORT, '0.0.0.0', () => {
  console.log(`\n🔊 Live Audio Share (WebRTC) :${PORT}`);
  console.log(`📱 Local  http://localhost:${PORT}`);
  const interfaces = os.networkInterfaces();
  for (const name in interfaces) {
    for (const net of interfaces[name]) {
      if (net.family === 'IPv4' && !net.internal) console.log(`🌐 ${name}  http://${net.address}:${PORT}`);
    }
  }
  console.log('\nHost: /  |  Listener: /listen');
});

module.exports = { app, server };
