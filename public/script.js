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

// Global variables
let currentVideoFile = null;
let networkAddresses = [];

// Initialize the app
document.addEventListener('DOMContentLoaded', function() {
    setupEventListeners();
    loadNetworkInfo();
    loadVideoList();
    checkCurrentVideo();
});

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
            showNotification('Please select a valid video file', 'error');
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
