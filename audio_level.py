"""audio_level.py -- Standalone audio level analyzer (sidecar process).

Owns ONE ffmpeg ebur128 analyzer on the requested DirectShow input and serves
the latest loudness as JSON on http://127.0.0.1:5005/level?device=NAME.

Why a separate process: inside the eventlet server, ANY blocking pipe read
-- native or green -- wedged the whole hub (proven via py-spy during
development). This process is plain stdlib (no eventlet): native threads +
blocking pipes are perfectly safe here. The server queries it over HTTP with
a short timeout, so even a dead sidecar can only cost one bounded wait.

Usage:  python audio_level.py [port]      (default 5005)
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FFMPEG = os.path.join(BASE_DIR, "tools", "ffmpeg", "bin", "ffmpeg.exe")
if not os.path.exists(FFMPEG):
    FFMPEG = "ffmpeg"

_state_lock = threading.Lock()
_state = {"device": None, "m": -120.0, "peak": -120.0, "at": 0.0,
          "last_try": 0.0}
_proc = None
_proc_lock = threading.Lock()


def _parse_line(line):
    m = re.search(r"\bM:\s*(-?\d+(?:\.\d+)?)", line)
    if m:
        try:
            with _state_lock:
                _state["m"] = float(m.group(1))
                _state["at"] = time.monotonic()
        except ValueError:
            pass
    p = re.search(r"\bTPK:\s*(-?\d+(?:\.\d+)?)", line)
    if p:
        try:
            with _state_lock:
                _state["peak"] = float(p.group(1))
                _state["at"] = time.monotonic()
        except ValueError:
            pass


def _reader(proc):
    try:
        for line in iter(proc.stderr.readline, ""):
            if not line:
                break
            _parse_line(line)
    except Exception:
        pass


def _spawn(device):
    flag = 0
    try:
        flag = subprocess.CREATE_NO_WINDOW
    except Exception:
        flag = 0
    return subprocess.Popen(
        [FFMPEG, "-hide_banner",
         "-f", "dshow", "-i", "audio=" + device,
         "-af", "ebur128=peak=true", "-f", "null", "-"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        creationflags=flag, universal_newlines=True, bufsize=1)


def ensure(device):
    """Analyzer on ``device`` running; True/False. Never blocks long."""
    global _proc
    if not device:
        return False
    with _proc_lock:
        if (_proc is not None and _state["device"] == device
                and _proc.poll() is None):
            return True
        now = time.monotonic()
        if now - _state["last_try"] < 2.0:
            return _proc is not None and _proc.poll() is None
        _state["last_try"] = now
        try:
            if _proc is not None:
                try:
                    _proc.terminate()
                    _proc.wait(timeout=2)
                except Exception:
                    try:
                        _proc.kill()
                    except Exception:
                        pass
            _proc = None
            with _state_lock:
                _state["device"] = None
                _state["m"] = -120.0
                _state["peak"] = -120.0
                _state["at"] = 0.0
            _proc = _spawn(device)
            with _state_lock:
                _state["device"] = device
            t = threading.Thread(target=_reader, args=(_proc,),
                                 name="level-reader", daemon=True)
            t.start()
            return True
        except Exception:
            _proc = None
            return False


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        try:
            q = parse_qs(urlparse(self.path).query)
            if urlparse(self.path).path.rstrip("/") != "/level":
                self._send(404, {"status": "not found"})
                return
            device = (q.get("device", [""])[0] or "").strip()
            if not device:
                self._send(400, {"status": "no device"})
                return
            if not ensure(device):
                self._send(500, {"device": device, "db": None,
                                 "peak": None, "live": False})
                return
            now = time.monotonic()
            with _state_lock:
                m, peak, at = _state["m"], _state["peak"], _state["at"]
            age = now - at if at else 999.0
            self._send(200, {"device": device, "db": round(m, 1),
                             "peak": round(peak, 1), "age": round(age, 2),
                             "live": age < 1.5})
        except Exception as e:
            try:
                self._send(500, {"status": "error: %s" % e})
            except Exception:
                pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5005
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    srv.daemon_threads = True
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
