const fs = require('fs');
let content = fs.readFileSync('server.js', 'utf8');

const newEvent = `
  socket.on('disconnect-viewer', ({ viewerId }) => {
    if (viewers.has(viewerId)) io.to(viewerId).emit('disconnect-request');
  });

  socket.on('tune-settings', (payload) => {
    if (socket.id !== hostSocketId) return;
    io.emit('tune-settings', payload);
  });
`;

content = content.replace("  socket.on('disconnect-viewer', ({ viewerId }) => {\n    if (viewers.has(viewerId)) io.to(viewerId).emit('disconnect-request');\n  });", newEvent);
fs.writeFileSync('server.js', content);
