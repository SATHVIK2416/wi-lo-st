const express = require('express');
const path = require('path');
const fs = require('fs');
const cors = require('cors');
const multer = require('multer');
const http = require('http');
const { Server } = require('socket.io');

const app = express();
const server = http.createServer(app);
const io = new Server(server, {
  cors: {
    origin: "*",
    methods: ["GET", "POST"]
  }
});
const PORT = process.env.PORT || 3000;

// Middleware
app.use(cors());
app.use(express.json());
app.use(express.static('public'));

// Store uploaded video information and connected clients
let currentVideo = null;
let connectedClients = new Set();
let isLiveStreamActive = false;

// Socket.io connection handling
io.on('connection', (socket) => {
  console.log('Client connected:', socket.id);
  connectedClients.add(socket.id);
  
  // Send current live stream status
  socket.emit('liveStreamStatus', { active: isLiveStreamActive });
  
  // Handle live audio stream
  socket.on('audioStream', (audioData) => {
    // Broadcast audio to all other connected clients
    socket.broadcast.emit('audioStream', audioData);
  });
  
  // Handle live stream start/stop
  socket.on('startLiveStream', () => {
    isLiveStreamActive = true;
    socket.broadcast.emit('liveStreamStarted');
    console.log('Live stream started by:', socket.id);
  });
  
  socket.on('stopLiveStream', () => {
    isLiveStreamActive = false;
    socket.broadcast.emit('liveStreamStopped');
    console.log('Live stream stopped by:', socket.id);
  });
  
  // Handle video synchronization
  socket.on('videoSync', (data) => {
    socket.broadcast.emit('videoSync', data);
  });
  
  socket.on('disconnect', () => {
    console.log('Client disconnected:', socket.id);
    connectedClients.delete(socket.id);
  });
});

// Configure multer for file uploads
const storage = multer.diskStorage({
  destination: function (req, file, cb) {
    const uploadDir = 'uploads';
    if (!fs.existsSync(uploadDir)) {
      fs.mkdirSync(uploadDir);
    }
    cb(null, uploadDir);
  },
  filename: function (req, file, cb) {
    // Keep original filename
    cb(null, file.originalname);
  }
});

const upload = multer({ 
  storage: storage,
  fileFilter: function (req, file, cb) {
    // Accept video files only - including MKV
    const allowedMimeTypes = [
      'video/mp4',
      'video/avi',
      'video/quicktime', // .mov
      'video/x-msvideo', // .avi
      'video/webm',
      'video/x-matroska', // .mkv
      'video/mp4', // .m4v
    ];
    
    const allowedExtensions = ['.mp4', '.avi', '.mov', '.mkv', '.webm', '.m4v'];
    const fileExtension = path.extname(file.originalname).toLowerCase();
    
    if (file.mimetype.startsWith('video/') || allowedMimeTypes.includes(file.mimetype) || allowedExtensions.includes(fileExtension)) {
      cb(null, true);
    } else {
      cb(new Error('Only video files are allowed! Supported formats: MP4, AVI, MOV, MKV, WebM, M4V'), false);
    }
  },
  limits: {
    fileSize: 5 * 1024 * 1024 * 1024 // 5GB limit
  }
});

// Routes
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

// Upload video file
app.post('/upload', upload.single('video'), (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: 'No video file uploaded' });
    }
    
    currentVideo = {
      filename: req.file.filename,
      originalName: req.file.originalname,
      path: req.file.path,
      size: req.file.size,
      mimetype: req.file.mimetype
    };
    
    console.log('Video uploaded:', currentVideo.originalName);
    res.json({ 
      message: 'Video uploaded successfully', 
      video: {
        name: currentVideo.originalName,
        size: currentVideo.size
      }
    });
  } catch (error) {
    console.error('Upload error:', error);
    res.status(500).json({ error: 'Upload failed' });
  }
});

// Get current video info
app.get('/current-video', (req, res) => {
  if (!currentVideo) {
    return res.status(404).json({ error: 'No video available' });
  }
  
  res.json({
    name: currentVideo.originalName,
    size: currentVideo.size
  });
});

// Stream video with range support
app.get('/stream/:filename', (req, res) => {
  const filename = req.params.filename;
  const videoPath = path.join(__dirname, 'uploads', filename);
  
  // Check if file exists
  if (!fs.existsSync(videoPath)) {
    return res.status(404).json({ error: 'Video not found' });
  }
  
  const stat = fs.statSync(videoPath);
  const fileSize = stat.size;
  const range = req.headers.range;
  
  if (range) {
    // Parse range header
    const parts = range.replace(/bytes=/, "").split("-");
    const start = parseInt(parts[0], 10);
    const end = parts[1] ? parseInt(parts[1], 10) : fileSize - 1;
    const chunksize = (end - start) + 1;
    
    // Create read stream for the requested range
    const file = fs.createReadStream(videoPath, { start, end });
    
    // Set appropriate headers for partial content
    const head = {
      'Content-Range': `bytes ${start}-${end}/${fileSize}`,
      'Accept-Ranges': 'bytes',
      'Content-Length': chunksize,
      'Content-Type': getMimeType(videoPath),
      'Cache-Control': 'no-cache'
    };
    
    res.writeHead(206, head);
    file.pipe(res);
  } else {
    // No range requested, send entire file
    const head = {
      'Content-Length': fileSize,
      'Content-Type': getMimeType(videoPath),
      'Cache-Control': 'no-cache'
    };
    
    res.writeHead(200, head);
    fs.createReadStream(videoPath).pipe(res);
  }
});

// Get list of available videos
app.get('/videos', (req, res) => {
  const uploadsDir = path.join(__dirname, 'uploads');
  
  if (!fs.existsSync(uploadsDir)) {
    return res.json([]);
  }
  
  try {
    const files = fs.readdirSync(uploadsDir);
    const videoFiles = files.filter(file => {
      const ext = path.extname(file).toLowerCase();
      return ['.mp4', '.avi', '.mov', '.mkv', '.webm', '.m4v', '.flv', '.wmv'].includes(ext);
    }).map(file => {
      const filePath = path.join(uploadsDir, file);
      const stat = fs.statSync(filePath);
      return {
        filename: file,
        size: stat.size,
        uploadDate: stat.mtime
      };
    });
    
    res.json(videoFiles);
  } catch (error) {
    console.error('Error reading videos directory:', error);
    res.status(500).json({ error: 'Failed to list videos' });
  }
});

// Delete video
app.delete('/videos/:filename', (req, res) => {
  const filename = req.params.filename;
  const videoPath = path.join(__dirname, 'uploads', filename);
  
  try {
    if (fs.existsSync(videoPath)) {
      fs.unlinkSync(videoPath);
      
      // Clear current video if it was deleted
      if (currentVideo && currentVideo.filename === filename) {
        currentVideo = null;
      }
      
      res.json({ message: 'Video deleted successfully' });
    } else {
      res.status(404).json({ error: 'Video not found' });
    }
  } catch (error) {
    console.error('Delete error:', error);
    res.status(500).json({ error: 'Failed to delete video' });
  }
});

// Get server network information
app.get('/network-info', (req, res) => {
  const os = require('os');
  const networkInterfaces = os.networkInterfaces();
  const addresses = [];
  
  for (const interfaceName in networkInterfaces) {
    const networkInterface = networkInterfaces[interfaceName];
    for (const network of networkInterface) {
      // Skip internal and non-IPv4 addresses
      if (!network.internal && network.family === 'IPv4') {
        addresses.push({
          interface: interfaceName,
          address: network.address,
          url: `http://${network.address}:${PORT}`
        });
      }
    }
  }
  
  res.json({
    port: PORT,
    addresses: addresses,
    localUrl: `http://localhost:${PORT}`
  });
});

// Get connected clients count
app.get('/clients-count', (req, res) => {
  res.json({ 
    count: connectedClients.size,
    liveStreamActive: isLiveStreamActive 
  });
});

// Helper function to get MIME type
function getMimeType(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  const mimeTypes = {
    '.mp4': 'video/mp4',
    '.avi': 'video/x-msvideo',
    '.mov': 'video/quicktime',
    '.mkv': 'video/x-matroska',
    '.webm': 'video/webm',
    '.m4v': 'video/mp4',
    '.flv': 'video/x-flv',
    '.wmv': 'video/x-ms-wmv'
  };
  return mimeTypes[ext] || 'video/mp4';
}

// Start server
server.listen(PORT, '0.0.0.0', () => {
  console.log(`🎥 Video Streaming Server is running!`);
  console.log(`📱 Local access: http://localhost:${PORT}`);
  
  // Show network addresses
  const os = require('os');
  const networkInterfaces = os.networkInterfaces();
  
  console.log('🌐 Network access:');
  for (const interfaceName in networkInterfaces) {
    const networkInterface = networkInterfaces[interfaceName];
    for (const network of networkInterface) {
      if (!network.internal && network.family === 'IPv4') {
        console.log(`   http://${network.address}:${PORT}`);
      }
    }
  }
  console.log('\n📂 Upload videos and stream live audio to connected devices!');
});

module.exports = { app, server };
