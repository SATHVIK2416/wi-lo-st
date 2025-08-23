const express = require('express');
const path = require('path');
const fs = require('fs');
const cors = require('cors');
const multer = require('multer');

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(cors());
app.use(express.json());
app.use(express.static('public'));

// Store uploaded video information
let currentVideo = null;

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
    // Accept video files only
    if (file.mimetype.startsWith('video/')) {
      cb(null, true);
    } else {
      cb(new Error('Only video files are allowed!'), false);
    }
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
      'Content-Type': 'video/mp4',
      'Cache-Control': 'no-cache'
    };
    
    res.writeHead(206, head);
    file.pipe(res);
  } else {
    // No range requested, send entire file
    const head = {
      'Content-Length': fileSize,
      'Content-Type': 'video/mp4',
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
      return ['.mp4', '.avi', '.mov', '.mkv', '.webm', '.m4v'].includes(ext);
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

// Start server
app.listen(PORT, '0.0.0.0', () => {
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
  console.log('\n📂 Upload videos and share the network URL with others on your WiFi!');
});

module.exports = app;
