"""
Wireless Music Server — YouTube proxy
--------------------------------------
Acts as a pure middleman: iOS sends a YouTube URL, server downloads it
via yt-dlp to a temp file, streams the audio back, then deletes it.
No songs folder, no persistent storage — deployable on Render free tier.

Deploy on Render:
  1. Push this file + requirements.txt to a GitHub repo
  2. New Web Service on render.com → connect repo → free tier
  3. Build command:  pip install -r requirements.txt
  4. Start command:  gunicorn server:app
  5. Paste the Render URL into the iOS app

Install locally:
  pip install flask yt-dlp gunicorn
"""

import os, sys, json, re, tempfile, threading
from pathlib import Path
from flask import Flask, Response, jsonify, request, stream_with_context

try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    HAS_YTDLP = False

app = Flask(__name__)

def sanitize(n):
    return re.sub(r'[\\/:*?"<>|]', "_", n).strip() or "track"


# ── CORS (needed for any browser client) ──────────────────────────────────────
@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"]  = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Range"
    return resp


# ── Ping — iOS checks this to confirm server is up + yt-dlp installed ─────────
@app.route("/api/ping")
def api_ping():
    return jsonify({
        "name":    "Wireless Proxy Server",
        "tracks":  0,          # no library — proxy only
        "ytdlp":   HAS_YTDLP,
        "version": 3,
        "mode":    "proxy",
    })


# ── Fetch — download one video and stream it back, then delete ────────────────
@app.route("/api/fetch")
def api_fetch():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    if not HAS_YTDLP:
        return jsonify({"error": "yt-dlp not installed on server"}), 500

    # Work in a per-request temp directory — cleaned up after streaming
    tmp_dir = tempfile.mkdtemp()

    ydl_opts = {
        # Prefer m4a (no ffmpeg needed); fall back to whatever is available
        "format":      "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
        "outtmpl":     os.path.join(tmp_dir, "%(title)s.%(ext)s"),
        "nooverwrites": True,
        "quiet":        True,
        "no_warnings":  True,
        # Don't try to merge/remux — avoids needing ffmpeg on the server
        "postprocessors": [],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title") or "track"
            ext   = info.get("ext")   or "m4a"
    except Exception as e:
        _cleanup(tmp_dir)
        return jsonify({"error": str(e)}), 500

    # Find the downloaded file
    files = list(Path(tmp_dir).iterdir())
    if not files:
        _cleanup(tmp_dir)
        return jsonify({"error": "Download produced no file"}), 500

    filepath = files[0]
    ext      = filepath.suffix.lstrip(".")
    safe     = sanitize(title)

    import mimetypes
    mime = mimetypes.guess_type(str(filepath))[0] or "audio/mp4"

    def generate():
        try:
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    yield chunk
        finally:
            _cleanup(tmp_dir)

    headers = {
        "Content-Disposition": f'attachment; filename="{safe}.{ext}"',
        "Content-Length":      str(filepath.stat().st_size),
        "X-Track-Title":       safe,
        "X-Track-Ext":         ext,
        "Cache-Control":       "no-store",
    }

    return Response(
        stream_with_context(generate()),
        mimetype=mime,
        headers=headers,
    )


def _cleanup(path):
    """Delete temp dir and all its contents."""
    try:
        import shutil
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


# ── Local dev entry point ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "127.0.0.1"

    print(f"\n{'─'*52}")
    print(f"  🎵  Wireless Proxy Server")
    print(f"{'─'*52}")
    print(f"  Local:   http://127.0.0.1:5000")
    print(f"  Network: http://{local_ip}:5000")
    print(f"  yt-dlp:  {'yes' if HAS_YTDLP else 'NO — pip install yt-dlp'}")
    print(f"  Mode:    proxy (no local storage)")
    print()

    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)