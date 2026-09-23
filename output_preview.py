"""output_preview.py — projection-monitor preview MJPEG feed for the PiP (additive).

The Picture-in-Picture box on custom_output.html must mirror the OUTPUT that is
being broadcast (the projection-monitor grab the real encoder pushes to
Facebook/YouTube), NOT the camera live input.  This sidecar process grabs the
same projection_monitor region (from config.json) with its own ffmpeg gdigrab
and re-serves it as a local HTTP MJPEG stream:

    GET /preview/feed.mjpeg    → infinite multipart/x-mixed-replace MJPEG
    GET /preview/snapshot.jpg  → single latest JPEG frame

It runs as a separate child process (like stream_server.py) so the infinite
stream never shares the eventlet hub with the main server.  The broadcast
encoder spawns it on start and kills the whole tree on stop, so the feed only
exists while a broadcast is actually live.

The PiP <img> on the output page points at ``http://<host>:<port>/preview/feed.mjpeg``.
"""

import json
import os
import subprocess
import sys
import threading
import time

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CONF_FILE = os.path.join(_BASE_DIR, "config.json")
_PREVIEW_PORT = int(os.environ.get("LEITURGIA_OUTPUT_PREVIEW_PORT", "5003"))
_PREVIEW_W = 960
_PREVIEW_H = 540
_FPS = 20


def _ffmpeg_path():
    try:
        with open(_CONF_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
        p = (cfg or {}).get("ffmpeg_path")
        if p:
            return p
    except Exception:
        pass
    bundled = os.path.join(_BASE_DIR, "tools", "ffmpeg", "bin", "ffmpeg.exe")
    if os.path.isfile(bundled):
        return bundled
    return os.environ.get("LEITURGIA_FFMPEG")


def _capture_monitor():
    try:
        with open(_CONF_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
        mon = (cfg or {}).get("projection_monitor")
    except Exception:
        mon = None
    if isinstance(mon, dict):
        x = int(mon.get("x", 0) or 0)
        y = int(mon.get("y", 0) or 0)
        w = int(mon.get("width", 1920) or 1920)
        h = int(mon.get("height", 1080) or 1080)
        return {"x": x, "y": y, "width": w, "height": h,
                "label": mon.get("label", "Monitor")}
    return {"x": 0, "y": 0, "width": 1920, "height": 1080,
            "label": "Monitor 1 (default)"}


# ── shared frame slot (producer: ffmpeg reader / consumer: HTTP) ─────────────
_AFTER_REQUEST = threading.Event()


class _Slot(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.frame = None
        self.fid = 0

    def set(self, frame):
        with self.lock:
            self.frame = frame
            self.fid += 1

    def get(self):
        with self.lock:
            return self.frame, self.fid


_SLOT = _Slot()


def _grab_loop(ffmpeg, mon):
    """Read a continuous JPEG stream from ffmpeg gdigrab and cache latest frame."""
    args = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "gdigrab", "-framerate", str(_FPS),
        "-offset_x", str(mon["x"]), "-offset_y", str(mon["y"]),
        "-video_size", "{}x{}".format(mon["width"], mon["height"]),
        "-draw_mouse", "0", "-i", "desktop",
        "-vf",
        "scale={}:{}:force_original_aspect_ratio=decrease,"
        "pad={}:{}:(ow-iw)/2:(oh-ih)/2".format(_PREVIEW_W, _PREVIEW_H, _PREVIEW_W, _PREVIEW_H),
        "-f", "mjpeg", "-q:v", "4", "pipe:1",
    ]
    creation = 0x08000000 if os.name == "nt" else 0
    proc = None
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL,
                                creationflags=creation, cwd=_BASE_DIR)
    except Exception:
        return
    buf = b""
    try:
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                if proc.poll() is not None:
                    break
                time.sleep(0.05)
                continue
            buf += chunk
            while True:
                s = buf.find(b"\xff\xd8\xff")
                if s < 0:
                    buf = b""
                    break
                e = buf.find(b"\xff\xd9", s + 3)
                if e < 0:
                    buf = buf[s:]
                    break
                _SLOT.set(buf[s:e + 2])
                buf = buf[e + 3:]
    except Exception:
        pass
    finally:
        try:
            if proc is not None and proc.poll() is None:
                proc.terminate()
        except Exception:
            pass
        _AFTER_REQUEST.set()


def _feed_generator(_):
    last_id = 0
    while True:
        frame, fid = _SLOT.get()
        if frame is not None and fid != last_id:
            last_id = fid
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: %d\r\n\r\n%s\r\n" % (len(frame), frame)
            )
        time.sleep(1.0 / max(1, _FPS))


def _run_server(ffmpeg, mon):
    global _PREVIEW_PORT
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class _H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/preview/snapshot.jpg":
                frame, _ = _SLOT.get()
                if frame is None:
                    self.send_response(204)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(frame)))
                self.end_headers()
                self.wfile.write(frame)
                return
            if path != "/preview/feed.mjpeg":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            try:
                for chunk in _feed_generator(self):
                    if not chunk:
                        continue
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError, ConnectionAbortedError):
                pass
            finally:
                try:
                    self.wfile.flush()
                except Exception:
                    pass

    class _Server(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    sock = None
    for _try_port in (_PREVIEW_PORT, _PREVIEW_PORT + 1, _PREVIEW_PORT + 2):
        try:
            sock = _Server(("0.0.0.0", _try_port), _H)
            _PREVIEW_PORT = _try_port
            break
        except OSError:
            continue
    if sock is None:
        sys.stderr.write("preview: no free port\n")
        return
    sys.stdout.write("preview ready on port %d\n" % _PREVIEW_PORT)
    sys.stdout.flush()
    gt = threading.Thread(target=_grab_loop, args=(ffmpeg, mon), daemon=True)
    gt.start()
    sock.serve_forever()
    _AFTER_REQUEST.wait()


def main():
    ffmpeg = _ffmpeg_path()
    if not ffmpeg or not os.path.isfile(ffmpeg):
        sys.stderr.write("preview: ffmpeg not found\n")
        sys.exit(1)
    mon = _capture_monitor()
    _run_server(ffmpeg, mon)


if __name__ == "__main__":
    main()