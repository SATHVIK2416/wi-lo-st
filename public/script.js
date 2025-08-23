// DOM Elements
const fileInput = document.getElementById('fileInput');
const uploadArea = document.getElementById('uploadArea');
const uploadProgress = document.getElementById('uploadProgress');
const progressFill = document.getElementById('progressFill');
const progressText = document.getElementById('progressText');
const videoPlayer = document.getElementById('videoPlayer');
const currentVideoInfo = document.getElementById('currentVideoInfo');
const videoList = document.getElementById('videoList');
const refreshListBtn = document.getElementById('refreshList');
const shareUrlInput = document.getElementById('shareUrlInput');
const copyUrlBtn = document.getElementById('copyUrl');
const networkInfo = document.getElementById('networkAddresses');

// Live Audio Elements
const startAudioBtn = document.getElementById('startAudioStream');
const stopAudioBtn = document.getElementById('stopAudioStream');
const audioStatus = document.getElementById('audioStatus');
const audioLevelBar = document.getElementById('audioLevelBar');
const liveAudioPlayer = document.getElementById('liveAudioPlayer');
const connectionStatus = document.getElementById('connectionStatus');
const clientsCount = document.getElementById('clientsCount');

// Global variables
let currentVideoFile = null;
let networkAddresses = [];
let socket = null;
let mediaStream = null;
let audioContext = null;
let analyser = null;
let isStreaming = false;

// Initialize the app
document.addEventListener('DOMContentLoaded', function() {
    setupEventListeners();
    initializeSocket();
    loadNetworkInfo();
    loadVideoList();
    checkCurrentVideo();
});

// Initialize Socket.IO connection
function initializeSocket() {
    socket = io();
    
    socket.on('connect', () => {
        console.log('Connected to server');
        connectionStatus.textContent = '🟢 Connected';
        connectionStatus.style.color = '#38a169';
        updateClientsCount();
    });
    
    socket.on('disconnect', () => {
        console.log('Disconnected from server');
        connectionStatus.textContent = '🔴 Disconnected';
        connectionStatus.style.color = '#e53e3e';
    });
    
    socket.on('audioStream', (audioData) => {
        playReceivedAudio(audioData);
    });
    
    socket.on('liveStreamStarted', () => {
        showNotification('Live audio stream started by another user', 'info');
    });
    
    socket.on('liveStreamStopped', () => {
        showNotification('Live audio stream stopped', 'info');
    });
    
    // Update clients count periodically
    setInterval(updateClientsCount, 5000);
}

// Setup event listeners
function setupEventListeners() {
    // File input and upload area
    uploadArea.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', handleFileSelect);
    
    // Drag and drop
    uploadArea.addEventListener('dragover', handleDragOver);
    uploadArea.addEventListener('dragleave', handleDragLeave);
    uploadArea.addEventListener('drop', handleFileDrop);
    
    // Other buttons
    refreshListBtn.addEventListener('click', loadVideoList);
    copyUrlBtn.addEventListener('click', copyShareUrl);
    
    // Audio streaming buttons
    startAudioBtn.addEventListener('click', startAudioStreaming);
    stopAudioBtn.addEventListener('click', stopAudioStreaming);
}

// Handle file selection
function handleFileSelect(event) {
    const file = event.target.files[0];
    if (file) {
        uploadFile(file);
    }
}

// Handle drag over
function handleDragOver(event) {
    event.preventDefault();
    uploadArea.classList.add('dragover');
}

// Handle drag leave
function handleDragLeave(event) {
    event.preventDefault();
    uploadArea.classList.remove('dragover');
}

// Handle file drop
function handleFileDrop(event) {
    event.preventDefault();
    uploadArea.classList.remove('dragover');
    
    const files = event.dataTransfer.files;
    if (files.length > 0) {
        const file = files[0];
        if (file.type.startsWith('video/')) {
            uploadFile(file);
        } else {
            showNotification('Please select a valid video file (MP4, AVI, MOV, MKV, WebM, M4V, FLV, WMV)', 'error');
        }
    }
}

// Upload file
function uploadFile(file) {
    const formData = new FormData();
    formData.append('video', file);
    
    // Show progress
    uploadProgress.style.display = 'block';
    progressFill.style.width = '0%';
    progressText.textContent = '0%';
    
    // Create XMLHttpRequest for progress tracking
    const xhr = new XMLHttpRequest();
    
    // Track upload progress
    xhr.upload.addEventListener('progress', function(e) {
        if (e.lengthComputable) {
            const percentComplete = (e.loaded / e.total) * 100;
            progressFill.style.width = percentComplete + '%';
            progressText.textContent = Math.round(percentComplete) + '%';
        }
    });
    
    // Handle completion
    xhr.addEventListener('load', function() {
        uploadProgress.style.display = 'none';
        
        if (xhr.status === 200) {
            const response = JSON.parse(xhr.responseText);
            showNotification('Video uploaded successfully!', 'success');
            currentVideoFile = response.video;
            updateCurrentVideoInfo();
            loadVideoList();
        } else {
            const error = JSON.parse(xhr.responseText);
            showNotification('Upload failed: ' + error.error, 'error');
        }
    });
    
    // Handle errors
    xhr.addEventListener('error', function() {
        uploadProgress.style.display = 'none';
        showNotification('Upload failed due to network error', 'error');
    });
    
    // Send request
    xhr.open('POST', '/upload');
    xhr.send(formData);
}

// Load network information
async function loadNetworkInfo() {
    try {
        const response = await fetch('/network-info');
        const data = await response.json();
        
        networkAddresses = data.addresses;
        
        let html = `<div class="network-address">
            <strong>Local:</strong> ${data.localUrl}
        </div>`;
        
        data.addresses.forEach(addr => {
            html += `<div class="network-address">
                <strong>${addr.interface}:</strong> ${addr.url}
            </div>`;
        });
        
        networkInfo.innerHTML = html;
        
        // Set share URL to the first network address or localhost
        const shareUrl = data.addresses.length > 0 ? data.addresses[0].url : data.localUrl;
        shareUrlInput.value = shareUrl;
        
    } catch (error) {
        console.error('Failed to load network info:', error);
        networkInfo.innerHTML = '<div class="network-address"><strong>Error:</strong> Could not load network information</div>';
    }
}

// Check current video
async function checkCurrentVideo() {
    try {
        const response = await fetch('/current-video');
        if (response.ok) {
            const data = await response.json();
            currentVideoFile = data;
            updateCurrentVideoInfo();
        }
    } catch (error) {
        console.error('Failed to check current video:', error);
    }
}

// Update current video info
function updateCurrentVideoInfo() {
    if (currentVideoFile) {
        currentVideoInfo.innerHTML = `
            <p class="video-name">📹 ${currentVideoFile.name}</p>
            <p class="video-size">📊 Size: ${formatFileSize(currentVideoFile.size)}</p>
        `;
        
        // Update video player source
        videoPlayer.style.display = 'block';
        videoPlayer.src = `/stream/${encodeURIComponent(currentVideoFile.name)}`;
        
        // Update share URL with video
        updateShareUrl();
    } else {
        currentVideoInfo.innerHTML = '<p>No video loaded</p>';
        videoPlayer.style.display = 'none';
        videoPlayer.src = '';
    }
}

// Load video list
async function loadVideoList() {
    try {
        const response = await fetch('/videos');
        const videos = await response.json();
        
        if (videos.length === 0) {
            videoList.innerHTML = '<p>No videos available</p>';
            return;
        }
        
        let html = '';
        videos.forEach(video => {
            const uploadDate = new Date(video.uploadDate).toLocaleDateString();
            html += `
                <div class="video-item">
                    <div class="video-item-info">
                        <div class="video-item-name">${video.filename}</div>
                        <div class="video-item-meta">
                            📊 ${formatFileSize(video.size)} • 📅 ${uploadDate}
                        </div>
                    </div>
                    <div class="video-item-actions">
                        <button class="btn btn-primary btn-small" onclick="playVideo('${video.filename}', ${video.size})">
                            ▶️ Play
                        </button>
                        <button class="btn btn-danger btn-small" onclick="deleteVideo('${video.filename}')">
                            🗑️ Delete
                        </button>
                    </div>
                </div>
            `;
        });
        
        videoList.innerHTML = html;
        
    } catch (error) {
        console.error('Failed to load video list:', error);
        videoList.innerHTML = '<p>Error loading videos</p>';
    }
}

// Play video
function playVideo(filename, size) {
    currentVideoFile = {
        name: filename,
        size: size
    };
    updateCurrentVideoInfo();
    showNotification(`Now playing: ${filename}`, 'info');
}

// Delete video
async function deleteVideo(filename) {
    if (!confirm(`Are you sure you want to delete "${filename}"?`)) {
        return;
    }
    
    try {
        const response = await fetch(`/videos/${encodeURIComponent(filename)}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showNotification('Video deleted successfully', 'success');
            loadVideoList();
            
            // Clear current video if it was deleted
            if (currentVideoFile && currentVideoFile.name === filename) {
                currentVideoFile = null;
                updateCurrentVideoInfo();
            }
        } else {
            const error = await response.json();
            showNotification('Failed to delete video: ' + error.error, 'error');
        }
    } catch (error) {
        console.error('Delete error:', error);
        showNotification('Failed to delete video', 'error');
    }
}

// Update share URL
function updateShareUrl() {
    if (currentVideoFile && networkAddresses.length > 0) {
        const baseUrl = networkAddresses[0].url;
        const videoUrl = `${baseUrl}/stream/${encodeURIComponent(currentVideoFile.name)}`;
        shareUrlInput.value = videoUrl;
    }
}

// Copy share URL
function copyShareUrl() {
    shareUrlInput.select();
    shareUrlInput.setSelectionRange(0, 99999); // For mobile devices
    
    try {
        document.execCommand('copy');
        showNotification('URL copied to clipboard!', 'success');
    } catch (error) {
        console.error('Copy failed:', error);
        showNotification('Failed to copy URL', 'error');
    }
}

// Format file size
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// Show notification
function showNotification(message, type = 'info') {
    const notification = document.getElementById('notification');
    notification.textContent = message;
    notification.className = `notification ${type}`;
    notification.classList.add('show');
    
    setTimeout(() => {
        notification.classList.remove('show');
    }, 3000);
}

// Error handling for video player
videoPlayer.addEventListener('error', function(e) {
    console.error('Video player error:', e);
    showNotification('Error playing video. Please try again.', 'error');
});

// Video player events
videoPlayer.addEventListener('loadstart', function() {
    console.log('Video loading started');
});

videoPlayer.addEventListener('canplay', function() {
    console.log('Video can start playing');
});

videoPlayer.addEventListener('loadedmetadata', function() {
    console.log('Video metadata loaded');
});

// Live Audio Streaming Functions - System Audio Capture
async function startAudioStreaming() {
    try {
        // Request screen share with audio to capture system audio
        mediaStream = await navigator.mediaDevices.getDisplayMedia({ 
            video: true, // We need video to get audio, but we'll only use audio
            audio: {
                echoCancellation: false,
                noiseSuppression: false,
                autoGainControl: false,
                suppressLocalAudioPlayback: false
            } 
        });
        
        // Check if audio track is available
        const audioTracks = mediaStream.getAudioTracks();
        if (audioTracks.length === 0) {
            throw new Error('No audio track available. Make sure to check "Share audio" when selecting screen/window.');
        }
        
        // Create audio-only stream
        const audioOnlyStream = new MediaStream();
        audioTracks.forEach(track => audioOnlyStream.addTrack(track));
        
        // Setup audio context for visualization
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const source = audioContext.createMediaStreamSource(audioOnlyStream);
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);
        
        // Setup MediaRecorder for streaming audio only
        const mediaRecorder = new MediaRecorder(audioOnlyStream, {
            mimeType: 'audio/webm;codecs=opus'
        });
        
        mediaRecorder.ondataavailable = function(event) {
            if (event.data.size > 0 && socket) {
                const reader = new FileReader();
                reader.onload = function() {
                    socket.emit('audioStream', reader.result);
                };
                reader.readAsArrayBuffer(event.data);
            }
        };
        
        // Start recording in chunks
        mediaRecorder.start(100); // Send audio data every 100ms
        
        // Stop video track to save resources (we only need audio)
        const videoTracks = mediaStream.getVideoTracks();
        videoTracks.forEach(track => track.stop());
        
        isStreaming = true;
        startAudioBtn.style.display = 'none';
        stopAudioBtn.style.display = 'inline-flex';
        audioStatus.textContent = '🔊 Streaming system audio...';
        audioStatus.style.color = '#e53e3e';
        
        // Start audio level visualization
        visualizeAudioLevel();
        
        // Notify other clients
        socket.emit('startLiveStream');
        
        showNotification('System audio streaming started! Play any video/music and it will be shared.', 'success');
        
        // Handle stream end (when user stops screen sharing)
        mediaStream.getVideoTracks().forEach(track => {
            track.onended = () => {
                stopAudioStreaming();
            };
        });
        
        audioOnlyStream.getAudioTracks().forEach(track => {
            track.onended = () => {
                stopAudioStreaming();
            };
        });
        
    } catch (error) {
        console.error('Error starting system audio stream:', error);
        if (error.name === 'NotAllowedError') {
            showNotification('Screen sharing was denied. Please allow screen sharing to capture system audio.', 'error');
        } else if (error.message.includes('No audio track')) {
            showNotification('No audio track found. Make sure to check "Share audio" when selecting screen/window.', 'error');
        } else {
            showNotification('Failed to start system audio stream: ' + error.message, 'error');
        }
    }
}

function stopAudioStreaming() {
    if (mediaStream) {
        mediaStream.getTracks().forEach(track => track.stop());
        mediaStream = null;
    }
    
    if (audioContext) {
        audioContext.close();
        audioContext = null;
    }
    
    isStreaming = false;
    startAudioBtn.style.display = 'inline-flex';
    stopAudioBtn.style.display = 'none';
    audioStatus.textContent = '🔇 System audio not shared';
    audioStatus.style.color = '#718096';
    audioLevelBar.style.width = '0%';
    
    // Notify other clients
    if (socket) {
        socket.emit('stopLiveStream');
    }
    
    showNotification('System audio streaming stopped', 'info');
}

function visualizeAudioLevel() {
    if (!analyser || !isStreaming) return;
    
    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    
    function updateLevel() {
        if (!isStreaming) return;
        
        analyser.getByteFrequencyData(dataArray);
        
        // Calculate average volume
        const average = dataArray.reduce((sum, value) => sum + value, 0) / bufferLength;
        const percentage = (average / 255) * 100;
        
        audioLevelBar.style.width = percentage + '%';
        
        requestAnimationFrame(updateLevel);
    }
    
    updateLevel();
}

function playReceivedAudio(audioData) {
    try {
        const audioBlob = new Blob([audioData], { type: 'audio/webm;codecs=opus' });
        const audioUrl = URL.createObjectURL(audioBlob);
        
        // Create temporary audio element for playback
        const audio = new Audio(audioUrl);
        audio.play().catch(error => {
            console.error('Error playing received audio:', error);
        });
        
        // Clean up URL after playing
        audio.addEventListener('ended', () => {
            URL.revokeObjectURL(audioUrl);
        });
        
    } catch (error) {
        console.error('Error playing received audio:', error);
    }
}

async function updateClientsCount() {
    try {
        const response = await fetch('/clients-count');
        const data = await response.json();
        clientsCount.textContent = `👥 ${data.count} connected`;
    } catch (error) {
        console.error('Failed to update clients count:', error);
    }
}
