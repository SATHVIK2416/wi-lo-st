/**
 * Live Audio Share Server
 * WebRTC signaling + static file host for low-latency system audio broadcast
 */
'use strict';

const express = require('express');
const path = require('path');
const http = require('http');
const { Server } = require('socket.io');
const os = require('os');

// ─────────────────────────────────────────────────────────────
// Configuration
// ─────────────────────────────────────────────────────────────
const PORT = process.env.PORT || 3000;
const SESSION_MAX_AGE = 24 * 60 * 60 * 1000; // 24 hours
const SESSION_CLEANUP_INTERVAL = 5 * 60 * 1000; // 5 minutes

// ─────────────────────────────────────────────────────────────
// Server Setup
// ─────────────────────────────────────────────────────────────
const app = express();
const server = http.createServer(app);
const io = new Server(server, {
  cors: { origin: '*' },
  pingTimeout: 60000,
  pingInterval: 25000
});

app.use(express.json());

// ─────────────────────────────────────────────────────────────
// State
// ─────────────────────────────────────────────────────────────
let hostSocketId = null;
const sessions = new Map();
const viewers = new Map();
const viewerStats = new Map();

// ─────────────────────────────────────────────────────────────
// Utilities
// ─────────────────────────────────────────────────────────────
const isLocalhost = (req) => {
  const ip = req.ip;
  return ip === '127.0.0.1' || ip === '::1' || ip === '::ffff:127.0.0.1' || req.hostname === 'localhost';
};

const getNetworkAddresses = () => {
  const interfaces = os.networkInterfaces();
  const addresses = [];
  for (const name in interfaces) {
    for (const net of interfaces[name]) {
      if (net.family === 'IPv4' && !net.internal) {
        addresses.push({ interface: name, address: net.address, url: `http://${net.address}:${PORT}` });
      }
    }
  }
  return addresses;
};

const broadcastStats = () => {
  io.emit('stats', {
    viewerCount: viewers.size,
    hostPresent: !!hostSocketId,
    viewerIds: [...viewers.keys()]
  });
};

// ─────────────────────────────────────────────────────────────
// Session Cleanup
// ─────────────────────────────────────────────────────────────
setInterval(() => {
  const now = Date.now();
  for (const [id, session] of sessions) {
    if (now - session.createdAt > SESSION_MAX_AGE) {
      sessions.delete(id);
    }
  }
}, SESSION_CLEANUP_INTERVAL);

// ─────────────────────────────────────────────────────────────
// Middleware
// ─────────────────────────────────────────────────────────────
const requireHostAccess = (req, res, next) => {
  if (isLocalhost(req)) return next();

  const sessionId = req.query.session || req.headers['x-session-id'];
  if (sessionId && sessions.get(sessionId)?.role === 'host') return next();

  res.redirect('/listen');
};

app.use(express.static(path.join(__dirname, 'public'), { index: false }));

// ─────────────────────────────────────────────────────────────
// Socket.IO Events
// ─────────────────────────────────────────────────────────────
io.on('connection', (socket) => {
  console.log('🔌 Connected:', socket.id);

  socket.on('register-host', () => {
    if (hostSocketId && hostSocketId !== socket.id) {
      console.log('⚠️  Replacing host:', hostSocketId);
    }
    hostSocketId = socket.id;
    console.log('🎙️  Host registered:', socket.id);
    socket.emit('host-confirmed');
    broadcastStats();
  });

  socket.on('announce-streaming', () => {
    if (socket.id !== hostSocketId) return;
    viewers.forEach((_, vid) => io.to(hostSocketId).emit('viewer-joined', { viewerId: vid }));
    io.emit('host-streaming');
  });

  socket.on('host-stopped-streaming', () => {
    if (socket.id !== hostSocketId) return;
    console.log('⏹️  Host stopped streaming');
    viewers.forEach((_, vid) => io.to(vid).emit('host-stopped'));
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

  socket.on('listener-stats', (payload) => {
    if (!hostSocketId) return;
    viewerStats.set(socket.id, { ...payload, timestamp: Date.now() });
    io.to(hostSocketId).emit('listener-stats', { viewerId: socket.id, ...payload });
  });

  socket.on('disconnect-viewer', ({ viewerId }) => {
    if (viewers.has(viewerId)) io.to(viewerId).emit('disconnect-request');
  });

  socket.on('disconnect', () => {
    if (socket.id === hostSocketId) {
      console.log('❌ Host disconnected');
      hostSocketId = null;
      viewers.forEach((_, vid) => io.to(vid).emit('host-left'));
      viewers.clear();
      viewerStats.clear();
    } else if (viewers.has(socket.id)) {
      console.log('👋 Viewer left:', socket.id);
      viewers.delete(socket.id);
      viewerStats.delete(socket.id);
      if (hostSocketId) io.to(hostSocketId).emit('viewer-left', { viewerId: socket.id });
    }
    broadcastStats();
  });
});

// ─────────────────────────────────────────────────────────────
// Routes
// ─────────────────────────────────────────────────────────────
app.get('/network-info', (_, res) => {
  res.json({ addresses: getNetworkAddresses(), localUrl: `http://localhost:${PORT}` });
});

app.get('/stats', (_, res) => {
  res.json({ viewerCount: viewers.size, hostPresent: !!hostSocketId, uptime: process.uptime() });
});

app.get('/health', (_, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

app.get('/', requireHostAccess, (_, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

app.get('/listen', (_, res) => {
  res.sendFile(path.join(__dirname, 'public', 'listen.html'));
});

// ─────────────────────────────────────────────────────────────
// Startup
// ─────────────────────────────────────────────────────────────
server.listen(PORT, '0.0.0.0', () => {
  const addrs = getNetworkAddresses();

  console.log('\n═══════════════════════════════════════════════');
  console.log('🔊  Live Audio Share (WebRTC)');
  console.log('═══════════════════════════════════════════════');
  console.log(`\n📱 Local: http://localhost:${PORT}`);

  if (addrs.length) {
    console.log('\n🌐 Network:');
    addrs.forEach(({ interface: iface, url }) => console.log(`   ${iface}: ${url}`));
  }

  console.log('\n📋 Endpoints: / | /listen | /stats | /health');
  console.log('═══════════════════════════════════════════════\n');
});

// Graceful shutdown
process.on('SIGTERM', () => {
  console.log('SIGTERM received, shutting down...');
  server.close(() => process.exit(0));
});

module.exports = { app, server };
