const fs = require('fs');
let content = fs.readFileSync('server.js', 'utf8');

const oldStr = `  socket.on('disconnect-viewer', ({ viewerId }) => {
    if (viewers.has(viewerId)) io.to(viewerId).emit('disconnect-request');
  });`;

const newStr = `  socket.on('disconnect-viewer', ({ viewerId }) => {
    if (viewers.has(viewerId)) io.to(viewerId).emit('disconnect-request');
  });

  socket.on('tune-settings', (payload) => {
    if (socket.id !== hostSocketId) return;
    io.emit('tune-settings', payload);
  });`;

content = content.replace(oldStr, newStr);
fs.writeFileSync('server.js', content);
