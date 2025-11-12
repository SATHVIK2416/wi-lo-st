// WebRTC signaling + static file host for low-latency system audio broadcast
const express = require('express');
const path = require('path');
const http = require('http');
const { Server } = require('socket.io');
const os = require('os');

const app = express();
const server = http.createServer(app);
const io = new Server(server, { 
  cors: { origin: '*' },
  pingTimeout: 60000,
  pingInterval: 25000
});
const PORT = process.env.PORT || 3000;

// Middleware
app.use(express.json());

// Session management for access control
const sessions = new Map(); // sessionId -> { role: 'host' | 'listener', createdAt }

// Middleware to protect host control page
const requireHostAccess = (req, res, next) => {
  const sessionId = req.query.session || req.headers['x-session-id'];
  
  // Check if request is coming from same machine (localhost)
  const isLocalhost = req.ip === '127.0.0.1' || 
                      req.ip === '::1' || 
                      req.ip === '::ffff:127.0.0.1' ||
                      req.hostname === 'localhost';
  
  // Allow access from localhost or with valid host session
  if (isLocalhost) {
    return next();
  }
  
  if (sessionId && sessions.has(sessionId)) {
    const session = sessions.get(sessionId);
    if (session.role === 'host') {
      return next();
    }
  }
  
  // Redirect to listener page for unauthorized access
  return res.redirect('/listen');
};

// Static files (excluding index.html which needs protection)
app.use(express.static(path.join(__dirname, 'public'), {
  index: false // Don't serve index.html automatically
}));

// State management
let hostSocketId = null;
const viewers = new Map(); // viewerId -> { createdAt, nickname }
const viewerStats = new Map(); // viewerId -> latest stats

// Clean up expired sessions every 5 minutes
setInterval(() => {
  const now = Date.now();
  const maxAge = 24 * 60 * 60 * 1000; // 24 hours
  for (const [id, session] of sessions.entries()) {
    if (now - session.createdAt > maxAge) {
      sessions.delete(id);
    }
  }
}, 5 * 60 * 1000);

// Socket.IO connection handler
io.on('connection', socket => {
  console.log('🔌 Connection established:', socket.id);

  socket.on('register-host', () => {
    if (hostSocketId && hostSocketId !== socket.id) {
      console.log('⚠️  Host already exists, replacing:', hostSocketId);
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
    // Notify all viewers that streaming has stopped
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

  // Listener periodically reports quality stats -> forward to host
  socket.on('listener-stats', payload => {
    if (hostSocketId) {
      viewerStats.set(socket.id, { ...payload, timestamp: Date.now() });
      io.to(hostSocketId).emit('listener-stats', { viewerId: socket.id, ...payload });
    }
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
      broadcastStats();
    } else if (viewers.has(socket.id)) {
      console.log('👋 Viewer disconnected:', socket.id);
      viewers.delete(socket.id);
      viewerStats.delete(socket.id);
      if (hostSocketId) io.to(hostSocketId).emit('viewer-left', { viewerId: socket.id });
      broadcastStats();
    }
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
  res.json({ 
    viewerCount: viewers.size, 
    hostPresent: !!hostSocketId,
    uptime: process.uptime()
  });
});

app.get('/health', (_req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// Protected host control page - only accessible from localhost or with valid session
app.get('/', requireHostAccess, (_req, res) => res.sendFile(path.join(__dirname, 'public', 'index.html')));

// Public listener page - accessible to everyone
app.get('/listen', (_req, res) => res.sendFile(path.join(__dirname, 'public', 'listen.html')));

server.listen(PORT, '0.0.0.0', () => {
  console.log('\n═══════════════════════════════════════════════');
  console.log('🔊  Live Audio Share (WebRTC)');
  console.log('═══════════════════════════════════════════════');
  console.log(`\n📱 Local Access:\n   http://localhost:${PORT}`);
  
  const interfaces = os.networkInterfaces();
  const networkAddrs = [];
  for (const name in interfaces) {
    for (const net of interfaces[name]) {
      if (net.family === 'IPv4' && !net.internal) {
        networkAddrs.push({ name, url: `http://${net.address}:${PORT}` });
      }
    }
  }
  
  if (networkAddrs.length > 0) {
    console.log('\n🌐 Network Access:');
    networkAddrs.forEach(({ name, url }) => console.log(`   ${name}: ${url}`));
  }
  
  console.log('\n📋 Endpoints:');
  console.log('   Host Control: /');
  console.log('   Listener:     /listen');
  console.log('   Stats:        /stats');
  console.log('   Health:       /health');
  console.log('\n═══════════════════════════════════════════════\n');
});

// Graceful shutdown
process.on('SIGTERM', () => {
  console.log('SIGTERM received, closing server...');
  server.close(() => {
    console.log('Server closed');
    process.exit(0);
  });
});

module.exports = { app, server };
