# app.py
import os
import shutil
import secrets
import time
import yt_dlp
import threading
import tempfile
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, send_file, jsonify, send_from_directory, Response
import base64
import json
import zipfile
import io
import requests



app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# Configuration
UPLOAD_FOLDER = 'uploads'
DOWNLOAD_FOLDER = 'downloads'
ALLOWED_EXTENSIONS = {'txt'}
MAX_AGE_HOURS = 2  # Files older than this will be cleaned up

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['DOWNLOAD_FOLDER'] = DOWNLOAD_FOLDER

# Create necessary directories
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
os.makedirs('static/img', exist_ok=True)

# Create a placeholder image if it doesn't exist
placeholder_path = os.path.join('static', 'img', 'video-placeholder.jpg')
if not os.path.exists(placeholder_path):
    # Simple 1x1 pixel JPEG
    placeholder_data = b'\xff\xd8\xff\xe0\x00\x10\x4a\x46\x49\x46\x00\x01\x01\x01\x00\x48\x00\x48\x00\x00\xff\xdb\x00\x43\x00\x03\x02\x02\x03\x02\x02\x03\x03\x03\x03\x04\x03\x03\x04\x05\x08\x05\x05\x04\x04\x05\x0a\x07\x07\x06\x08\x0c\x0a\x0c\x0c\x0b\x0a\x0b\x0b\x0d\x0e\x12\x10\x0d\x0e\x11\x0e\x0b\x0b\x10\x16\x10\x11\x13\x14\x15\x15\x15\x0c\x0f\x17\x18\x16\x14\x18\x12\x14\x15\x14\xff\xdb\x00\x43\x01\x03\x04\x04\x05\x04\x05\x09\x05\x05\x09\x14\x0d\x0b\x0d\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\x14\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01\xff\xc4\x00\x15\x00\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08\xff\xc4\x00\x14\x10\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xc4\x00\x14\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xc4\x00\x14\x11\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00\xb2\xc0\x00\x00\x00\x00\x00\x00\x00\x00\xff\xd9'
    with open(placeholder_path, 'wb') as f:
        f.write(placeholder_data)

# Store active downloads
active_downloads = {}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def clean_old_files():
    """Remove files older than MAX_AGE_HOURS"""
    current_time = time.time()
    max_age = MAX_AGE_HOURS * 3600
    
    # Clean downloads folder
    for item in os.listdir(app.config['DOWNLOAD_FOLDER']):
        item_path = os.path.join(app.config['DOWNLOAD_FOLDER'], item)
        if os.path.isfile(item_path) or os.path.isdir(item_path):
            creation_time = os.path.getctime(item_path)
            if (current_time - creation_time) > max_age:
                try:
                    if os.path.isfile(item_path):
                        os.remove(item_path)
                    else:
                        shutil.rmtree(item_path)
                except Exception as e:
                    print(f"Error removing {item_path}: {e}")
    
    # Clean uploads folder
    for item in os.listdir(app.config['UPLOAD_FOLDER']):
        item_path = os.path.join(app.config['UPLOAD_FOLDER'], item)
        if os.path.isfile(item_path):
            creation_time = os.path.getctime(item_path)
            if (current_time - creation_time) > max_age:
                try:
                    os.remove(item_path)
                except Exception as e:
                    print(f"Error removing {item_path}: {e}")

def extract_playlist_info(session_id, playlist_url, cookie_path=None, browser_name=None):
    """Extract info from YouTube playlist and provide direct download links"""
    
    active_downloads[session_id] = {
        'status': 'starting',
        'progress': 0,
        'videos': [],
        'current_video': '',
        'completed': False,
        'error': None,
    }
    
    # Configure yt-dlp options
    ydl_opts = {
        'quiet': True,
        'extract_flat': False,  # We need full video info
        'skip_download': True,  # Don't download, just extract info
        'format': 'best',
    }
    
    # Add cookies if provided as file
    if cookie_path:
        ydl_opts['cookiefile'] = cookie_path
    
    # Add browser cookie extraction if browser specified
    if browser_name:
        ydl_opts['cookiesfrombrowser'] = (browser_name, None, None, None)
        active_downloads[session_id]['status'] = 'getting_cookies'
        
    try:
        active_downloads[session_id]['status'] = 'getting_info'
        
        # Extract playlist info
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(playlist_url, download=False)
            
            if 'entries' in info:
                videos = info['entries']
                active_downloads[session_id]['total_videos'] = len(videos)
                
                # Process each video to get direct download URLs
                for video in videos:
                    # Store information about each video
                    active_downloads[session_id]['videos'].append({
                        'id': video['id'],
                        'title': video['title'],
                        'url': video['webpage_url'],
                        'thumbnail': video.get('thumbnail', ''),
                        'duration': video.get('duration', 0),
                        'formats': [
                            {
                                'format_id': f['format_id'],
                                'url': f['url'],
                                'ext': f.get('ext', 'mp4'),
                                'resolution': f'{f.get("width", "?")}x{f.get("height", "?")}',
                                'filesize': f.get('filesize', 0)
                            }
                            for f in video.get('formats', []) 
                            if f.get('url') and not f.get('acodec') == 'none'  # Exclude audio-only formats
                        ]
                    })
            else:
                # Single video
                active_downloads[session_id]['total_videos'] = 1
                active_downloads[session_id]['videos'].append({
                    'id': info['id'],
                    'title': info['title'],
                    'url': info['webpage_url'],
                    'thumbnail': info.get('thumbnail', ''),
                    'duration': info.get('duration', 0),
                    'formats': [
                        {
                            'format_id': f['format_id'],
                            'url': f['url'],
                            'ext': f.get('ext', 'mp4'),
                            'resolution': f'{f.get("width", "?")}x{f.get("height", "?")}',
                            'filesize': f.get('filesize', 0)
                        }
                        for f in info.get('formats', []) 
                        if f.get('url') and not f.get('acodec') == 'none'  # Exclude audio-only formats
                    ]
                })
                
        # Update status
        active_downloads[session_id]['status'] = 'ready'
        active_downloads[session_id]['progress'] = 100
        active_downloads[session_id]['completed'] = True
        
    except Exception as e:
        active_downloads[session_id]['status'] = 'error'
        active_downloads[session_id]['error'] = str(e)
        print(f"Error extracting playlist info: {e}")
        
@app.route('/direct-download/<session_id>/<video_id>/<format_id>')
def direct_download(session_id, video_id, format_id):
    """Handle direct download of a video"""
    if session_id not in active_downloads:
        return render_template('index.html', error="Download session not found")
    
    # Find the video and format
    for video in active_downloads[session_id]['videos']:
        if video['id'] == video_id:
            for fmt in video['formats']:
                if fmt['format_id'] == format_id:
                    # Create a response that downloads the video
                    filename = f"{video['title']}.{fmt['ext']}"
                    safe_filename = secure_filename(filename)
                    
                    # Download the video content
                    try:
                        response = requests.get(fmt['url'], stream=True)
                        if response.status_code == 200:
                            # Create a response with the video content
                            return Response(
                                response.content,
                                mimetype=f'video/{fmt["ext"]}',
                                headers={
                                    "Content-Disposition": f'attachment; filename="{safe_filename}"',
                                    "Content-Type": f'video/{fmt["ext"]}'
                                }
                            )
                    except Exception as e:
                        print(f"Error downloading video: {e}")
                        return render_template('index.html', error=f"Error downloading video: {e}")
    
    return render_template('index.html', error="Video format not found")

@app.route('/')
def index():
    # Run cleanup
    clean_old_files()
    return render_template('index.html')

@app.route('/cookie-helper')
def cookie_helper():
    """Show instructions for exporting cookies"""
    return render_template('cookie_helper.html')

@app.route('/browser-profiles')
def browser_profiles():
    """Show available browser profiles for cookie extraction"""
    browsers = []
    
    # Common browser paths by OS
    os_paths = {
        'windows': {
            'chrome': ['%LOCALAPPDATA%\\Google\\Chrome\\User Data', 
                       '%USERPROFILE%\\AppData\\Local\\Google\\Chrome\\User Data'],
            'firefox': ['%APPDATA%\\Mozilla\\Firefox\\Profiles'],
            'edge': ['%LOCALAPPDATA%\\Microsoft\\Edge\\User Data'],
            'brave': ['%LOCALAPPDATA%\\BraveSoftware\\Brave-Browser\\User Data']
        },
        'macos': {
            'chrome': ['~/Library/Application Support/Google/Chrome'],
            'firefox': ['~/Library/Application Support/Firefox/Profiles'],
            'edge': ['~/Library/Application Support/Microsoft Edge'],
            'brave': ['~/Library/Application Support/BraveSoftware/Brave-Browser']
        },
        'linux': {
            'chrome': ['~/.config/google-chrome', '~/.config/chrome'],
            'firefox': ['~/.mozilla/firefox'],
            'edge': ['~/.config/microsoft-edge'],
            'brave': ['~/.config/BraveSoftware/Brave-Browser']
        }
    }
    
    # Detect OS and check browser paths
    import platform
    import os
    
    system = platform.system().lower()
    if 'windows' in system:
        os_type = 'windows'
    elif 'darwin' in system:
        os_type = 'macos'
    else:
        os_type = 'linux'
    
    # Expand environment variables in paths
    import re
    
    def expand_path(path):
        if os_type == 'windows':
            # Handle Windows environment variables
            def replace_env_var(match):
                return os.environ.get(match.group(1), '')
            
            path = re.sub(r'%([^%]+)%', replace_env_var, path)
        else:
            # Handle Unix-style paths
            path = os.path.expanduser(path)
        
        return path
    
    # Check for each browser
    for browser, paths in os_paths[os_type].items():
        for path in paths:
            expanded_path = expand_path(path)
            if os.path.exists(expanded_path):
                browsers.append({
                    'name': browser.capitalize(),
                    'path': path,
                    'exists': True
                })
                break
        else:
            browsers.append({
                'name': browser.capitalize(),
                'path': None,
                'exists': False
            })
    
    return render_template('browser_profiles.html', browsers=browsers, os_type=os_type)

@app.route('/download', methods=['POST'])
def download():
    playlist_url = request.form.get('playlist_url')
    
    if not playlist_url:
        return render_template('index.html', error="Please enter a playlist URL")
    
    # Create a unique session ID
    session_id = secrets.token_hex(8)
    
    # Get browser selection
    browser_name = request.form.get('browser')
    
    # Check if cookie file was uploaded
    cookie_path = None
    if 'cookie_file' in request.files:
        file = request.files['cookie_file']
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            cookie_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{session_id}_{filename}")
            file.save(cookie_path)
    
    # Start extracting playlist info in a separate thread
    thread = threading.Thread(target=extract_playlist_info, args=(session_id, playlist_url, cookie_path, browser_name))
    thread.daemon = True
    thread.start()
    
    return redirect(url_for('download_status', session_id=session_id))

@app.route('/status/<session_id>')
def download_status(session_id):
    if session_id not in active_downloads:
        return render_template('index.html', error="Download session not found")
    
    return render_template('status.html', session_id=session_id)

@app.route('/api/status/<session_id>')
def api_status(session_id):
    if session_id not in active_downloads:
        return jsonify({'error': 'Download session not found'}), 404
    
    return jsonify(active_downloads[session_id])

@app.route('/download-all/<session_id>')
def download_all(session_id):
    """Generate a download script for all videos"""
    if session_id not in active_downloads:
        return render_template('index.html', error="Download session not found")
    
    videos = active_downloads[session_id]['videos']
    if not videos:
        return render_template('index.html', error="No videos found to download")
    
    if request.user_agent.platform in ['windows', 'win', 'windows NT']:
        # Windows batch script
        script_content = "@echo off\n"
        script_content += "echo Downloading all videos...\n"
        
        # Add download commands
        for video in videos:
            best_format = None
            # Find best format
            if video['formats']:
                # Sort formats by resolution or filesize
                sorted_formats = sorted(video['formats'], 
                                       key=lambda f: int(f['resolution'].split('x')[1]) if 'x' in f['resolution'] and f['resolution'].split('x')[1].isdigit() else 0, 
                                       reverse=True)
                best_format = sorted_formats[0]
            
            if best_format:
                safe_title = secure_filename(video['title'])
                script_content += f'echo Downloading: {safe_title}\n'
                script_content += f'curl -L -o "{safe_title}.{best_format["ext"]}" "{best_format["url"]}"\n'
                script_content += 'if %errorlevel% neq 0 echo Failed to download: {}\n'.format(safe_title)
                script_content += 'echo.\n'
        
        script_content += "echo All downloads completed!\n"
        script_content += "pause\n"
        
        # Create a response with the batch script
        response = Response(script_content, mimetype='text/plain')
        response.headers["Content-Disposition"] = f"attachment; filename=download_all_videos.bat"
        return response
    else:
        # Shell script for Linux/MacOS
        script_content = "#!/bin/bash\n"
        script_content += "echo \"Downloading all videos...\"\n"
        
        # Add download commands
        for video in videos:
            best_format = None
            # Find best format
            if video['formats']:
                # Sort formats by resolution or filesize
                sorted_formats = sorted(video['formats'], 
                                       key=lambda f: int(f['resolution'].split('x')[1]) if 'x' in f['resolution'] and f['resolution'].split('x')[1].isdigit() else 0, 
                                       reverse=True)
                best_format = sorted_formats[0]
            
            if best_format:
                safe_title = secure_filename(video['title']).replace('"', '\\"')
                script_content += f'echo "Downloading: {safe_title}"\n'
                script_content += f'curl -L -o "{safe_title}.{best_format["ext"]}" "{best_format["url"]}"\n'
                script_content += 'if [ $? -ne 0 ]; then echo "Failed to download: {}" ; fi\n'.format(safe_title)
                script_content += 'echo ""\n'
        
        script_content += "echo \"All downloads completed!\"\n"
        
        # Create a response with the shell script
        response = Response(script_content, mimetype='text/plain')
        response.headers["Content-Disposition"] = f"attachment; filename=download_all_videos.sh"
        return response

@app.route('/direct-download-all/<session_id>')
def direct_download_all(session_id):
    """Download all videos in a playlist directly"""
    if session_id not in active_downloads:
        return render_template('index.html', error="Download session not found")
    
    videos = active_downloads[session_id]['videos']
    if not videos:
        return render_template('index.html', error="No videos found to download")
    
    # Check if specific videos were selected
    selected_video_ids = request.args.get('selected', '').split(',')
    if selected_video_ids and selected_video_ids[0]:
        # Filter videos to only include selected ones
        videos = [v for v in videos if v['id'] in selected_video_ids]
    
    def generate():
        try:
            # Create a BytesIO object to store the ZIP file
            memory_file = io.BytesIO()
            
            with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
                total_videos = len(videos)
                for index, video in enumerate(videos, 1):
                    # Find best format
                    best_format = None
                    if video['formats']:
                        # Sort formats by resolution or filesize
                        sorted_formats = sorted(video['formats'], 
                                           key=lambda f: int(f['resolution'].split('x')[1]) if 'x' in f['resolution'] and f['resolution'].split('x')[1].isdigit() else 0, 
                                           reverse=True)
                        best_format = sorted_formats[0]
                    
                    if best_format:
                        # Update progress
                        progress = (index / total_videos) * 100
                        active_downloads[session_id]['current_video'] = video['title']
                        active_downloads[session_id]['progress'] = progress
                        
                        # Download the video
                        safe_title = secure_filename(video['title'])
                        filename = f"{safe_title}.{best_format['ext']}"
                        
                        try:
                            response = requests.get(best_format['url'], stream=True)
                            if response.status_code == 200:
                                # Add the video to the ZIP file
                                zf.writestr(filename, response.content)
                        except Exception as e:
                            print(f"Error downloading {filename}: {e}")
                            active_downloads[session_id]['error'] = f"Error downloading {filename}: {e}"
            
            # Seek to the beginning of the BytesIO object
            memory_file.seek(0)
            
            # Yield the ZIP file content
            while True:
                chunk = memory_file.read(8192)
                if not chunk:
                    break
                yield chunk
                
        except Exception as e:
            print(f"Error creating ZIP file: {e}")
            active_downloads[session_id]['error'] = str(e)
    
    # Create a response with the ZIP file
    response = Response(
        generate(),
        mimetype='application/zip',
        headers={
            "Content-Disposition": f"attachment; filename=playlist_videos.zip",
            "Content-Type": "application/zip"
        }
    )
    return response

@app.route('/download-video/<session_id>/<video_id>/<format_id>')
def download_video(session_id, video_id, format_id):
    """Download a single video with a specific format"""
    if session_id not in active_downloads:
        return render_template('index.html', error="Download session not found")
    
    # Find the video and format
    for video in active_downloads[session_id]['videos']:
        if video['id'] == video_id:
            for fmt in video['formats']:
                if fmt['format_id'] == format_id:
                    # Create a response that downloads the video
                    filename = f"{video['title']}.{fmt['ext']}"
                    safe_filename = secure_filename(filename)
                    
                    def generate():
                        try:
                            response = requests.get(fmt['url'], stream=True)
                            if response.status_code == 200:
                                total_size = int(response.headers.get('content-length', 0))
                                block_size = 8192
                                downloaded = 0
                                
                                for data in response.iter_content(block_size):
                                    downloaded += len(data)
                                    yield data
                                    
                                    # Update progress in active_downloads
                                    if total_size > 0:
                                        progress = (downloaded / total_size) * 100
                                        active_downloads[session_id]['current_video'] = video['title']
                                        active_downloads[session_id]['progress'] = progress
                                    
                        except Exception as e:
                            print(f"Error downloading video: {e}")
                            active_downloads[session_id]['error'] = str(e)
                    
                    return Response(
                        generate(),
                        mimetype=f'video/{fmt["ext"]}',
                        headers={
                            "Content-Disposition": f'attachment; filename="{safe_filename}"',
                            "Content-Type": f'video/{fmt["ext"]}'
                        }
                    )
    
    return render_template('index.html', error="Video format not found")

if __name__ == '__main__':
    app.run(debug=True)


