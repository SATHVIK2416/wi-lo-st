# 🎥 Video Stream WebApp with Live Audio

A comprehensive web application that allows you to upload video files from your file explorer and stream them over your local network (WiFi), plus **live audio streaming** from your laptop to all connected devices in real-time!

## ✨ Enhanced Features

- 📁 **File Upload**: Drag and drop or click to select video files from your computer
- 🎬 **Video Streaming**: Stream videos with adaptive quality and seek support  
- 🎤 **Live Audio Streaming**: Stream your laptop's audio live to all connected devices
- 🌐 **Network Sharing**: Share videos and audio with anyone on your local WiFi network
- 📱 **Responsive Design**: Works on desktop, tablet, and mobile devices
- 🎯 **Extended Format Support**: MP4, AVI, MOV, **MKV**, WebM, M4V, FLV, WMV
- 📊 **File Management**: View, play, and delete uploaded videos
- 🔗 **Easy Sharing**: Copy direct video URLs to share with others
- 👥 **Real-time Connection Status**: See how many devices are connected
- 🎚️ **Audio Level Visualization**: See live audio levels while streaming

## 🚀 Quick Start

### Prerequisites

- Node.js (version 14 or higher)
- NPM (comes with Node.js)
- Modern web browser with WebRTC support
- Microphone access (for live audio streaming)

### Installation

1. **Install dependencies:**
   ```bash
   npm install
   ```

2. **Start the server:**
   ```bash
   npm start
   ```

   Or for development with auto-restart:
   ```bash
   npm run dev
   ```

3. **Access the application:**
   - Local access: http://localhost:3000
   - Network access: Check the console output for your network IP addresses

## 📖 How to Use

### 1. Starting the Server
Run `npm start` and note the network URLs displayed in the console. These URLs can be used by others on your WiFi network.

### 2. Uploading Videos
- **Method 1**: Click the upload area and select a video file
- **Method 2**: Drag and drop a video file onto the upload area

Supported formats: MP4, AVI, MOV, **MKV**, WebM, M4V, FLV, WMV

### 3. Live Audio Streaming
- Click "🎙️ Start Live Audio" to begin streaming your laptop's audio
- Allow microphone access when prompted
- Your audio will be streamed live to all connected devices
- Watch the audio level visualization to see streaming activity
- Click "⏹️ Stop Live Audio" to end the stream

### 4. Playing Videos
- Once uploaded, the video will appear in the "Current Video" section
- Use the built-in video player to watch locally
- Videos are also listed in the "Available Videos" section

### 5. Sharing with Others
- Copy the URL from the "Share Video" section
- Send this URL to others on your WiFi network
- They can access videos AND hear live audio directly in their browser
- Real-time connection counter shows how many devices are connected

### 6. Managing Videos
- View all uploaded videos in the "Available Videos" section
- Click "Play" to switch to a different video
- Click "Delete" to remove videos you no longer need

## 🌐 Network Access

When you start the server, it will display URLs like:
```
🎥 Video Streaming Server is running!
📱 Local access: http://localhost:3000
🌐 Network access:
   http://192.168.1.100:3000
   http://10.0.0.50:3000

📂 Upload videos and stream live audio to connected devices!
```

Share the network URLs with others on your WiFi network so they can access videos and hear live audio streams.

## 📁 File Structure

```
wi-lo-st/
├── server.js              # Main server file
├── package.json           # Dependencies and scripts
├── public/                # Frontend files
│   ├── index.html         # Main HTML page
│   ├── styles.css         # CSS styling
│   └── script.js          # JavaScript functionality
├── uploads/               # Uploaded videos (created automatically)
└── README.md              # This file
```

## 🛠️ Technical Details

### Backend (Node.js/Express)
- **File Upload**: Multer middleware for handling file uploads
- **Video Streaming**: HTTP range requests for efficient streaming
- **Live Audio Streaming**: Socket.IO for real-time audio transmission
- **WebRTC Integration**: Modern audio streaming with low latency
- **CORS**: Cross-origin resource sharing enabled
- **File Management**: REST API for video operations

### Frontend (HTML/CSS/JavaScript)
- **Responsive Design**: Mobile-friendly interface
- **Drag & Drop**: Modern file upload experience
- **Progress Tracking**: Real-time upload progress
- **Video Player**: HTML5 video with full controls
- **Live Audio Interface**: Real-time audio streaming controls
- **WebSocket Communication**: Socket.IO for live features
- **Audio Visualization**: Real-time audio level indicators

### Streaming Technology
- **Range Requests**: Supports seeking and progressive download
- **Multiple Formats**: Extended format support including MKV
- **Real-time Audio**: WebRTC-based audio streaming
- **Adaptive Quality**: Browser handles quality based on network
- **Low Latency**: Optimized for real-time communication

## 🔧 Configuration

### Port Configuration
Change the port by setting the PORT environment variable:
```bash
PORT=8080 npm start
```

### File Size Limits
The default file upload limit is handled by Express. To change it, modify the server.js file.

### Supported Video Formats
The app supports common video formats including:
- MP4 (recommended)
- AVI
- MOV
- **MKV** (newly added)
- WebM
- M4V
- FLV
- WMV

### Live Audio Features
- **Real-time Streaming**: Audio streams with minimal delay
- **Audio Level Visualization**: See live audio activity
- **Multi-device Support**: Stream to unlimited connected devices
- **Echo Cancellation**: Built-in audio processing for better quality

## 🚨 Security Notes

- This app is designed for local network use only
- Don't expose it to the internet without proper security measures
- Uploaded files are stored locally on the server
- No authentication is implemented (suitable for trusted networks)

## 🐛 Troubleshooting

### Video Won't Play
- Ensure the video format is supported (including MKV)
- Check if the file was uploaded successfully
- Try refreshing the page

### Live Audio Not Working
- Ensure microphone access is granted
- Check if browser supports WebRTC
- Verify other devices are connected to the same network
- Try refreshing all connected devices

### Can't Access from Other Devices
- Make sure all devices are on the same WiFi network
- Check Windows Firewall settings
- Verify the server is running and displaying network URLs

### Upload Fails
- Check available disk space
- Ensure the video file isn't corrupted
- Try a smaller file size

## 📞 Support

If you encounter issues:
1. Check the console output for error messages
2. Ensure all dependencies are installed correctly
3. Verify network connectivity between devices

## 🎯 Use Cases

- **Home Entertainment**: Share movies with family members + live commentary
- **Presentations**: Stream videos during meetings with live audio narration
- **Education**: Share educational content in classrooms with teacher audio
- **Events**: Display videos at parties with live DJ commentary
- **Gaming**: Stream gameplay with live voice commentary
- **Music Sessions**: Share music videos with live audio mixing
- **Development**: Test video and audio streaming functionality

## 🔄 Updates

To update the application:
1. Pull the latest changes
2. Run `npm install` to update dependencies
3. Restart the server

---

**Enjoy streaming your videos! 🎬**
