// WebRTC Signaling + Static Hosting Server (Audio Broadcast)
const express = require('express');
const path = require('path');
const http = require('http');
const { Server } = require('socket.io');
const os = require('os');

const app = express();
const server = http.createServer(app);
const io = new Server(server, { cors: { origin: '*' } });
const PORT = process.env.PORT || 3000;

app.use(express.static('public'));

// Track host socket (only one broadcaster) and peer connections meta
let hostSocketId = null;
// Maintain map of viewerId -> simple metadata (createdAt)
const viewers = new Map();

io.on('connection', socket => {
  console.log('🔌 Socket connected', socket.id);

  // Host announces itself
  socket.on('register-host', () => {
    hostSocketId = socket.id;
    console.log('🎙️ Host registered:', socket.id);
    socket.emit('host-confirmed');
  broadcastStats();
  });

  // Viewer joins; server notifies host to create an offer
  socket.on('viewer-join', () => {
    if (!hostSocketId) {
      socket.emit('no-host');
      return;
    }
    viewers.set(socket.id, { createdAt: Date.now() });
    io.to(hostSocketId).emit('viewer-joined', { viewerId: socket.id });
  broadcastStats();
  });

  // Host sends offer to specific viewer
  socket.on('webrtc-offer', ({ viewerId, sdp }) => {
    io.to(viewerId).emit('webrtc-offer', { sdp, hostId: socket.id });
  });

  // Viewer sends answer back
  socket.on('webrtc-answer', ({ hostId, sdp }) => {
    io.to(hostId).emit('webrtc-answer', { sdp, viewerId: socket.id });
  });

  // ICE candidates relay
  socket.on('webrtc-ice-candidate', ({ targetId, candidate }) => {
    if (targetId) io.to(targetId).emit('webrtc-ice-candidate', { candidate, from: socket.id });
  });

  // Host can request viewer removal
  socket.on('disconnect-viewer', ({ viewerId }) => {
    if (viewers.has(viewerId)) io.to(viewerId).emit('disconnect-request');
  });

  socket.on('disconnect', () => {
    if (socket.id === hostSocketId) {
      console.log('❌ Host disconnected');
      hostSocketId = null;
      // Notify all viewers host is gone
      viewers.forEach((_, vid) => io.to(vid).emit('host-left'));
      viewers.clear();
      broadcastStats();
    } else if (viewers.has(socket.id)) {
      viewers.delete(socket.id);
      if (hostSocketId) io.to(hostSocketId).emit('viewer-left', { viewerId: socket.id });
      broadcastStats();
    }
    console.log('🔌 Socket disconnected', socket.id);
  });
});

function broadcastStats() {
  io.emit('stats', { viewerCount: viewers.size, hostPresent: !!hostSocketId });
}

// Helper route for LAN addresses
app.get('/network-info', (req, res) => {
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

// Simple stats endpoint
app.get('/stats', (req, res) => {
  res.json({ viewerCount: viewers.size, hostPresent: !!hostSocketId });
});

app.get('/', (_, res) => res.sendFile(path.join(__dirname, 'public', 'index.html')));
app.get('/listen', (_, res) => res.sendFile(path.join(__dirname, 'public', 'listen.html')));

server.listen(PORT, '0.0.0.0', () => {
  console.log(`\n🔊 Live Audio Share (WebRTC) running on port ${PORT}`);
  console.log(`📱 Local: http://localhost:${PORT}`);
  const interfaces = os.networkInterfaces();
  console.log('🌐 Network:');
  for (const name in interfaces) {
    for (const net of interfaces[name]) {
      if (net.family === 'IPv4' && !net.internal) console.log(`   http://${net.address}:${PORT}`);
    }
  }
  console.log('\nOpen / in a modern Chromium-based browser to host, /listen to join.');
});

module.exports = { app, server };
