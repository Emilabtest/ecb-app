"""projection_feed.py — Server-rendered projection MJPEG feed (additive).

The broadcast encoder and the output-page Picture-in-Picture used to grab the
*physical* projection monitor with ffmpeg gdigrab (output_preview.py). When the
OS mirrors/duplicates the displays, that grabs the whole desktop, so the
broadcast showed the operator screen instead of the congregation content.

This child process instead renders the projection channel page (``/ch1``) inside
an invisible headless Microsoft Edge instance and re-serves that render as its
own self-contained MJPEG HTTP feed -- the projection view, independent of any
physical monitor, window, or display-mirroring state:

    GET /projection/feed.mjpeg    multipart/x-mixed-replace MJPEG (browser/ffmpeg)
    GET /projection/feed.jpg      raw concatenated JPEG frames (ffmpeg fallback)
    GET /projection/snapshot.jpg  latest single JPEG frame
    GET /projection/status        JSON {serving, frames, source}

Implementation:
- Edge is started with a DevTools remote-debugging port; this script talks to the
  ``Page.captureScreenshot`` endpoint over a tiny stdlib-only WebSocket client
  (the spawned child may run under the base interpreter, so no third-party
  libraries are assumed).
- Doesn't touch compiled pymod/app.pyc.  Spawned by broadcast_encoder
  ``_spawn_preview()`` when a broadcast starts, killed on stop (same lifecycle
  as the old output_preview.py).
"""

import base64
import json
import os
import re
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CONF_FILE = os.path.join(_BASE_DIR, "config.json")

_FEED_PORT = int(os.environ.get("LEITURGIA_PROJ_FEED_PORT", "5004"))
_DEBUG_PORT = int(os.environ.get("LEITURGIA_PROJ_DEBUG_PORT", "9842"))
_CHANNEL = os.environ.get("LEITURGIA_PROJ_CHANNEL", "ch1")
_SERVER_PORT = os.environ.get("LEITURGIA_PORT", "5000")
_QUALITY = int(os.environ.get("LEITURGIA_PROJ_QUALITY", "70"))
_FRAME_INTERVAL = float(os.environ.get("LEITURGIA_PROJ_INTERVAL", "0.12"))


def _find_edge():
    candidates = [
        os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
        + "\\Microsoft\\Edge\\Application\\msedge.exe",
        os.environ.get("ProgramFiles", "C:\\Program Files")
        + "\\Microsoft\\Edge\\Application\\msedge.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "Microsoft", "Edge", "Application", "msedge.exe"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def _capture_size():
    try:
        with open(_CONF_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
        mon = (cfg or {}).get("projection_monitor")
    except Exception:
        mon = None
    if isinstance(mon, dict):
        w = int(mon.get("width", 1920) or 1920)
        h = int(mon.get("height", 1080) or 1080)
        return max(320, min(3840, w)), max(180, min(2160, h))
    return 1920, 1080


def _source_url():
    over = os.environ.get("LEITURGIA_PROJ_URL")
    if over:
        return over
    # Broadcast variant: mounts the PiP live box on pip pushes, while the
    # plain /ch1 projector / operator-monitor screens stay clean (see
    # IS_BROADCAST / handleLive in templates/projection.html).
    return "http://127.0.0.1:%s/%s?broadcast=1" % (_SERVER_PORT, _CHANNEL)


# ── minimal WebSocket client (RFC 6455, stdlib only) ─────────────────────────
class _WS(object):
    def __init__(self):
        self.sock = None

    def connect(self, host, port, path, timeout=16):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            "GET {} HTTP/1.1\r\n"
            "Host: {}:{}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: {}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).format(path, host, port, key)
        self.sock.sendall(req.encode("ascii"))
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("ws handshake failed")
            data += chunk
        head, _, _ = data.partition(b"\r\n\r\n")
        first, _, _ = head.partition(b"\r\n")
        if b" 101 " not in first:
            raise RuntimeError("ws handshake refused: %r" % head[:200])

    def _frame(self, payload, opcode):
        mask = os.urandom(4)
        n = len(payload)
        header = bytes([0x80 | opcode])
        if n < 126:
            header += bytes([0x80 | n])
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def send_text(self, text):
        self._frame(text.encode("utf-8"), 0x1)

    def recv_text(self, timeout=None):
        self.sock.settimeout(timeout)
        while True:
            b0 = self._read_exact(2)
            opcode = b0[0] & 0x0F
            length = b0[1] & 0x7F
            masked = bool(b0[1] & 0x80)
            if length == 126:
                length = struct.unpack(">H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read_exact(8))[0]
            m = b""
            if masked:
                m = self._read_exact(4)
            payload = self._read_exact(length)
            if masked:
                payload = bytes(payload[i] ^ m[i % 4] for i in range(len(payload)))
            if opcode == 0x9:  # ping
                self._frame(payload, 0xA)  # pong
                continue
            if opcode == 0x8:  # close
                raise RuntimeError("ws closed")
            if opcode in (0x1, 0x2):
                return payload.decode("utf-8", "replace")

    def _read_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise RuntimeError("ws read short")
            buf += chunk
        return buf

    def close(self):
        try:
            self._frame(b"", 0x8)
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


# ── shared frame slot (producer: CDP / consumer: HTTP) ───────────────────────
class _Slot(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.frame = None
        self.fid = 0
        self.failed = ""

    def set(self, frame):
        with self.lock:
            self.frame = frame
            self.fid += 1

    def get(self):
        with self.lock:
            return self.frame, self.fid


_SLOT = _Slot()
_AFTER_REQUEST = threading.Event()


def _find_page_ws(edge, debug_port, url):
    """Start Edge + locate the page's DevTools websocket URL."""
    profile = os.path.join(tempfile.gettempdir(),
                          "leitur-proj-feed-%d" % debug_port)
    args = [
        edge, "--headless=new",
        "--remote-debugging-port=%d" % debug_port,
        "--user-data-dir=%s" % profile,
        "--window-size=%dx%d" % _capture_size(),
        "--force-device-scale-factor=1",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-gpu",
        "--disable-features=Translate",
        "--mute-audio",
        url,
    ]
    creation = 0x08000000 if os.name == "nt" else 0
    subprocess.Popen(args, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL,
                     creationflags=creation, cwd=_BASE_DIR)
    deadline = time.time() + 25
    last_err = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d/json/list" % debug_port,
                    timeout=3) as r:
                targets = json.loads(r.read().decode("utf-8", "replace"))
            for t in targets:
                if (t.get("type") == "page"
                        and t.get("webSocketDebuggerUrl")
                        and (url in (t.get("url") or "") or "http" in (t.get("url") or ""))):
                    return t["webSocketDebuggerUrl"]
        except Exception as e:
            last_err = repr(e)
        time.sleep(0.6)
    return last_err or "no devtools target"


def _cmd_shot(ws, cmd_id):
    """Request one Page.captureScreenshot and block until the response arrives."""
    ws.send_text(json.dumps({
        "id": cmd_id,
        "method": "Page.captureScreenshot",
        "params": {"format": "jpeg", "quality": _QUALITY, "fromSurface": True},
    }))
    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            msg = ws.recv_text(timeout=6)
        except Exception:
            raise
        data = json.loads(msg)
        if data.get("id") == cmd_id:
            res = data.get("result") or {}
            b64 = res.get("data")
            if b64:
                _SLOT.set(base64.b64decode(b64))
            return True
        if data.get("method") == "Target.targetCrashed":
            raise RuntimeError("edge target crashed")
    return False


def _shot_loop(ws):
    """Roadrunner screenshot loop until the socket dies."""
    ws.send_text(json.dumps({"id": 1, "method": "Page.enable"}))
    time.sleep(0.5)
    cmd_id = 2
    while True:
        try:
            _cmd_shot(ws, cmd_id)
        except Exception:
            break
        cmd_id += 1
        time.sleep(max(0.02, _FRAME_INTERVAL))
    _AFTER_REQUEST.set()


def _produce():
    edge = _find_edge()
    if not edge:
        _SLOT.failed = "Edge not found"
        _AFTER_REQUEST.set()
        return
    url = _source_url()
    ws_url = _find_page_ws(edge, _DEBUG_PORT, url)
    if not ws_url or not ws_url.startswith("ws://"):
        _SLOT.failed = "devtools: %s" % ws_url
        _AFTER_REQUEST.set()
        return
    m = re.match(r"ws://([^:/]+):(\d+)(.*)$", ws_url)
    if not m:
        _SLOT.failed = "bad ws url: %s" % ws_url
        _AFTER_REQUEST.set()
        return
    ws = _WS()
    try:
        ws.connect(m.group(1), int(m.group(2)), m.group(3))
    except Exception as e:
        _SLOT.failed = "ws connect: %r" % e
        _AFTER_REQUEST.set()
        return
    try:
        _shot_loop(ws)
    finally:
        try:
            ws.close()
        except Exception:
            pass


def _feed_generator(step=1.0 / max(2.0, 1.0 / max(0.02, _FRAME_INTERVAL))):
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
        time.sleep(step)


class _H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send_jpeg(self, frame):
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(frame)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(frame)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/projection/snapshot.jpg", "/preview/snapshot.jpg"):
            frame, _ = _SLOT.get()
            if frame is None:
                self.send_response(204)
                self.end_headers()
                return
            self._send_jpeg(frame)
            return
        if path == "/projection/status":
            frame, fid = _SLOT.get()
            body = json.dumps({
                "serving": frame is not None,
                "frames": fid,
                "port": _FEED_PORT,
                "source": _source_url(),
                "failed": _SLOT.failed,
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in ("/projection/feed.raw", "/preview/feed.raw"):
            # Raw concatenated JPEG frames (no multipart boundary) so the
            # broadcast encoder's ffmpeg -f mjpeg can consume it directly.
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Cache-Control", "no-cache, no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            last_id = 0
            try:
                while True:
                    frame, fid = _SLOT.get()
                    if frame is not None and fid != last_id:
                        last_id = fid
                        self.wfile.write(frame)
                        self.wfile.flush()
                        time.sleep(max(0.01, _FRAME_INTERVAL))
                    else:
                        time.sleep(max(0.01, _FRAME_INTERVAL))
            except (BrokenPipeError, ConnectionResetError, OSError,
                    ConnectionAbortedError):
                pass
            finally:
                try:
                    self.wfile.flush()
                except Exception:
                    pass
            return
        if path not in ("/projection/feed.mjpeg", "/preview/feed.mjpeg"):
            self.send_error(404)
            return
        self.send_response(200)
        # Sending image/jpeg + multipart here is TWO content types; keep the
        # browser-friendly multipart feed for the PiP overlay only.
        self.send_header("Content-Type",
                         "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            for chunk in _feed_generator():
                if not chunk:
                    continue
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError,
                ConnectionAbortedError):
            pass
        finally:
            try:
                self.wfile.flush()
            except Exception:
                pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    global _FEED_PORT
    sock = None
    for _try in (_FEED_PORT, _FEED_PORT + 1, _FEED_PORT + 2):
        try:
            sock = _Server(("0.0.0.0", _try), _H)
            _FEED_PORT = _try
            break
        except OSError:
            continue
    if sock is None:
        sys.stderr.write("projfeed: no free port\n")
        sys.exit(1)
    sys.stdout.write("projfeed ready on port %d\n" % _FEED_PORT)
    sys.stdout.flush()
    threading.Thread(target=_produce, daemon=True).start()
    sock.serve_forever()
    _AFTER_REQUEST.wait()


if __name__ == "__main__":
    main()