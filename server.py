import http.server
import socketserver
import os
import json
import subprocess
import urllib.parse
import threading
import time
import signal
import random
import webbrowser
import hashlib
from pathlib import Path

PORT = 8000
VIDEO_DIR = os.path.expanduser("~/Videos")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
THUMBNAIL_DIR = os.path.join(BASE_DIR, "static", "thumbnails")
STATIC_DIR = os.path.join(BASE_DIR, "static")
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")
CACHE_FILE = os.path.join(BASE_DIR, "cache.json")
AUTOSTART_DIR = os.path.expanduser("~/.config/autostart")
AUTOSTART_FILE = os.path.join(AUTOSTART_DIR, "media-center.desktop")

# Ensure dirs exist
os.makedirs(THUMBNAIL_DIR, exist_ok=True)
os.makedirs(AUTOSTART_DIR, exist_ok=True)

class GifManager:
    def __init__(self):
        self.gif_dir = os.path.join(STATIC_DIR, "cat-gifs")
        self.gifs = []
        self.lock = threading.Lock()
        threading.Thread(target=self.scan_gifs, daemon=True).start()

    def scan_gifs(self):
        if not os.path.exists(self.gif_dir): return
        temp_gifs = []
        for entry in sorted(os.listdir(self.gif_dir)):
            if entry.lower().endswith(('.gif', '.png', '.jpg', '.jpeg', '.webp')):
                full_p = os.path.join(self.gif_dir, entry)
                duration = 3.0
                try:
                    res = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=duration', '-of', 'default=noprint_wrappers=1:nokey=1', full_p], capture_output=True, text=True, timeout=2)
                    if res.returncode == 0 and res.stdout.strip():
                        duration = float(res.stdout.strip())
                except: pass
                temp_gifs.append({'url': f"/static/cat-gifs/{entry}", 'duration': duration})
        random.shuffle(temp_gifs)
        with self.lock:
            self.gifs = temp_gifs

    def get_gifs(self):
        with self.lock:
            if not self.gifs:
                if not os.path.exists(self.gif_dir): return []
                res = [{'url': f"/static/cat-gifs/{e}", 'duration': 3.0} for e in sorted(os.listdir(self.gif_dir)) if e.lower().endswith(('.gif', '.png', '.jpg', '.jpeg', '.webp'))]
            else:
                res = list(self.gifs)
        random.shuffle(res)
        return res

gif_manager = GifManager()

class SettingsManager:
    def __init__(self):
        self.defaults = {"subtitles_enabled": True, "autostart": True, "music_enabled": True}
        self.settings = self.load()
        self.apply_startup()

    def load(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r') as f:
                    return {**self.defaults, **json.load(f)}
            except: pass
        return self.defaults.copy()

    def save(self, new_settings):
        self.settings.update(new_settings)
        with open(SETTINGS_FILE, 'w') as f: json.dump(self.settings, f)
        self.apply_startup()

    def apply_startup(self):
        if self.settings.get("autostart"):
            content = f"[Desktop Entry]\nType=Application\nName=Media Center\nExec={os.path.join(BASE_DIR, 'start.sh')}\nX-GNOME-Autostart-enabled=true\n"
            with open(AUTOSTART_FILE, 'w') as f: f.write(content)
            os.chmod(AUTOSTART_FILE, 0o755)
        elif os.path.exists(AUTOSTART_FILE): os.remove(AUTOSTART_FILE)

settings_mgr = SettingsManager()

def get_vid_id(rel_path):
    return hashlib.md5(rel_path.encode('utf-8')).hexdigest()

class CacheManager:
    def __init__(self):
        self.cache = self.load()
        self.lock = threading.Lock()

    def load(self):
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r') as f:
                    return json.load(f)
            except: pass
        return {"structure": {}, "last_scan": 0, "file_count": 0}

    def save(self):
        with open(CACHE_FILE, 'w') as f:
            json.dump(self.cache, f)

    def get_file_stats(self):
        count = 0
        latest_mod = 0
        if os.path.exists(VIDEO_DIR):
            for root, _, files in os.walk(VIDEO_DIR):
                for f in files:
                    if f.lower().endswith(('.mp4', '.webm', '.mkv')):
                        count += 1
                        mtime = os.path.getmtime(os.path.join(root, f))
                        if mtime > latest_mod: latest_mod = mtime
        return count, latest_mod

    def is_cache_valid(self):
        count, latest_mod = self.get_file_stats()
        return count == self.cache.get("file_count") and latest_mod <= self.cache.get("last_scan")

    def update_cache(self):
        count, latest_mod = self.get_file_stats()
        structure = {}
        for root, dirs, files in os.walk(VIDEO_DIR):
            rel_root = os.path.relpath(root, VIDEO_DIR)
            if rel_root == ".": rel_root = ""
            
            videos = []
            for f in files:
                if f.lower().endswith(('.mp4', '.webm', '.mkv')):
                    rel_p = os.path.relpath(os.path.join(root, f), VIDEO_DIR)
                    vid_id = get_vid_id(rel_p)
                    videos.append({
                        'id': vid_id,
                        'title': clean_title(f),
                        'rel_path': rel_p,
                        'thumbnail': f"/static/thumbnails/{vid_id}.jpg"
                    })
            
            structure[rel_root] = {
                'videos': videos,
                'folders': sorted([d for d in dirs if not d.startswith('.')]),
                'previews': []
            }

        all_vids_by_folder = {p: [v['thumbnail'] for v in data['videos']] for p, data in structure.items()}
        for rel_root in structure:
            previews = []
            for f_path, thumbs in all_vids_by_folder.items():
                if f_path == rel_root or (rel_root != "" and f_path.startswith(rel_root + "/")) or (rel_root == "" and f_path != ""):
                    for t in thumbs:
                        if os.path.exists(os.path.join(BASE_DIR, t.lstrip('/'))):
                            previews.append(t)
                            if len(previews) >= 4: break
                if len(previews) >= 4: break
            structure[rel_root]['previews'] = previews

        with self.lock:
            self.cache = {"structure": structure, "last_scan": time.time(), "file_count": count}
            self.save()

cache_mgr = CacheManager()
scan_progress = {'total': 0, 'completed': 0, 'ready': False}

class VLCManager:
    def __init__(self):
        self.process = None
        self.lock = threading.Lock()

    def play(self, video_path):
        self.stop()
        with self.lock:
            subs = settings_mgr.settings.get("subtitles_enabled", True)
            cmd = ['vlc', '--fullscreen', '--video-on-top', '--spu' if subs else '--no-spu',
                   '--sub-track=0' if subs else '--no-sub-autodetect-file', '--sub-language=en,eng',
                   '--play-and-exit', video_path]
            self.process = subprocess.Popen(cmd)

    def stop(self):
        with self.lock:
            if self.process:
                try: self.process.terminate()
                except: pass
                self.process = None

    def is_active(self):
        with self.lock:
            if self.process:
                if self.process.poll() is None: return True
                self.process = None
            return False

vlc_manager = VLCManager()

def clean_title(filename):
    return os.path.splitext(filename)[0].replace('.', ' ').replace('_', ' ').strip().title()

def generate_thumbnails_bg():
    global scan_progress
    if cache_mgr.is_cache_valid():
        scan_progress['ready'] = True; return

    all_videos = []
    if os.path.exists(VIDEO_DIR):
        for root, _, files in os.walk(VIDEO_DIR):
            for file in files:
                if file.lower().endswith(('.mp4', '.webm', '.mkv')): all_videos.append(os.path.join(root, file))
    
    scan_progress['total'] = len(all_videos)
    for full_path in all_videos:
        rel_p = os.path.relpath(full_path, VIDEO_DIR)
        vid_id = get_vid_id(rel_p)
        thumb_path = os.path.join(THUMBNAIL_DIR, f"{vid_id}.jpg")
        if not os.path.exists(thumb_path):
            try: subprocess.run(['ffmpeg', '-y', '-i', full_path, '-ss', '00:00:05', '-vframes', '1', '-vf', 'scale=320:-1', thumb_path], 
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            except: pass
        scan_progress['completed'] += 1
    
    cache_mgr.update_cache()
    scan_progress['ready'] = True

class MediaRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/api/settings':
            content_length = int(self.headers['Content-Length'])
            settings_mgr.save(json.loads(self.rfile.read(content_length)))
            self.send_response(200); self.end_headers(); self.wfile.write(b"OK"); return
        self.send_error(404)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path); path = parsed.path; query = urllib.parse.parse_qs(parsed.query)
        if path == '/api/status':
            self.send_response(200); self.send_header('Content-type', 'application/json'); self.end_headers()
            self.wfile.write(json.dumps({**scan_progress, 'vlc_active': vlc_manager.is_active()}).encode('utf-8')); return
        if path == '/api/youtube':
            webbrowser.open("https://www.youtube.com/tv")
            self.send_response(200); self.end_headers(); self.wfile.write(b"OK"); return
        if path == '/api/settings':
            self.send_response(200); self.send_header('Content-type', 'application/json'); self.end_headers()
            self.wfile.write(json.dumps(settings_mgr.settings).encode('utf-8')); return
        if path == '/api/exit':
            self.send_response(200); self.end_headers(); self.wfile.write(b"Exiting..."); 
            def shutdown():
                time.sleep(1); subprocess.run(['pkill', 'firefox']); os.kill(os.getpid(), signal.SIGTERM)
            threading.Thread(target=shutdown).start(); return
        if path == '/api/list':
            sub_path = query.get('path', [''])[0]; rel_path = urllib.parse.unquote(sub_path).strip('/')
            cached_data = cache_mgr.cache.get("structure", {}).get(rel_path)
            if cached_data:
                items = {'folders': [], 'videos': []}
                for folder_name in cached_data['folders']:
                    full_folder_rel = os.path.join(rel_path, folder_name).strip('/')
                    folder_info = cache_mgr.cache.get("structure", {}).get(full_folder_rel, {})
                    items['folders'].append({'name': folder_name, 'path': full_folder_rel, 'previews': folder_info.get('previews', [])})
                items['videos'] = cached_data['videos']
                for v in items['videos']:
                    if not os.path.exists(os.path.join(BASE_DIR, v['thumbnail'].lstrip('/'))): v['thumbnail'] = None
            else:
                current_dir = os.path.abspath(os.path.join(VIDEO_DIR, rel_path))
                if not current_dir.startswith(os.path.abspath(VIDEO_DIR)): self.send_error(403); return
                items = {'folders': [], 'videos': []}
                if os.path.exists(current_dir):
                    for entry in sorted(os.listdir(current_dir)):
                        full_p = os.path.join(current_dir, entry); item_rel_p = os.path.relpath(full_p, VIDEO_DIR)
                        if os.path.isdir(full_p) and not entry.startswith('.'):
                            items['folders'].append({'name': entry, 'path': item_rel_p, 'previews': []})
                        elif entry.lower().endswith(('.mp4', '.webm', '.mkv')):
                            vid_id = get_vid_id(item_rel_p)
                            items['videos'].append({'id': vid_id, 'title': clean_title(entry), 'rel_path': item_rel_p,
                                'thumbnail': f"/static/thumbnails/{vid_id}.jpg" if os.path.exists(os.path.join(THUMBNAIL_DIR, f"{vid_id}.jpg")) else None})
            res = json.dumps(items).encode('utf-8')
            self.send_response(200); self.send_header('Content-type', 'application/json'); self.end_headers(); self.wfile.write(res); return
        if path == '/api/play':
            rel_path = query.get('path', [None])[0]
            full_p = os.path.abspath(os.path.join(VIDEO_DIR, urllib.parse.unquote(rel_path)))
            if os.path.exists(full_p): vlc_manager.play(full_p)
            self.send_response(200); self.end_headers(); self.wfile.write(b"OK"); return
        if path == '/api/gifs':
            gifs = gif_manager.get_gifs(); res = json.dumps(gifs).encode('utf-8')
            self.send_response(200); self.send_header('Content-type', 'application/json'); self.end_headers(); self.wfile.write(res); return
        if path == '/api/stop':
            vlc_manager.stop(); self.send_response(200); self.end_headers(); self.wfile.write(b"Stopped"); return
        super().do_GET()

    def translate_path(self, path):
        p = urllib.parse.unquote(path.lstrip('/'))
        if p.startswith('static/'): p = p[7:]
        if not p or p == 'index.html': return os.path.join(STATIC_DIR, 'index.html')
        return os.path.join(STATIC_DIR, p)

class ThreadingSimpleServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    pass

if __name__ == "__main__":
    threading.Thread(target=generate_thumbnails_bg, daemon=True).start()
    os.chdir(BASE_DIR)
    with ThreadingSimpleServer(("", PORT), MediaRequestHandler) as httpd:
        print(f"Server with Exit Control running on port {PORT}", flush=True)
        httpd.serve_forever()

class ThreadingSimpleServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    pass

if __name__ == "__main__":
    threading.Thread(target=generate_thumbnails_bg, daemon=True).start()
    os.chdir(BASE_DIR)
    with ThreadingSimpleServer(("", PORT), MediaRequestHandler) as httpd:
        print(f"Server with Exit Control running on port {PORT}", flush=True)
        httpd.serve_forever()
