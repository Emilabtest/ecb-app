"""
live_input.py â€” Server-side live video capture & MJPEG streaming.

The original app.pyc only relays a *device_id* string to the projection clients,
and each projection.html browser then opened ``getUserMedia`` against its *own*
capture hardware. That breaks when the HDMI capture cards / webcams are plugged
into the *server* machine (the operator's PC), because the projection clients
(browsers on the projectors / LED wall) never see those devices.

This module solves that by capturing frames ON the server (where the capture
cards physically are) and relaying them to any client via MJPEG-over-HTTP.

It is deliberately written OUTSIDE the recovered app.pyc so the sourceless
module stays untouched. Wiring happens in server_entry.py / the operator
console (index.html) / the projection template (projection.html).

ARCHITECTURE
------------
* ``describe_sources()`` enumerates server-side capture devices via OpenCV.
* Each source that has at least one subscriber runs a *single* capture thread
  that pulls frames at ~target_fps, JPEG-encodes them, and stores the latest
  encoded byte string in a shared slot. Every HTTP subscriber yields that same
  slot, so N projection clients share ONE camera (no device contention).
* Because eventlet.monkey_patch() has already run in server_entry.py, we must
  NOT let a blocking OpenCV ``read()`` stall the green event loop. So the
  capture threads are real OS threads created with the *unpatched* threading
  module (captured below), and we communicate with them via a small helpers.

NOTE on importing order: server_entry.py imports this module BEFORE calling
``eventlet.monkey_patch()`` so that ``import threading`` here binds to the
real (non-green) threading module. This lets the capture threads block on
``cap.read()`` without freezing the socketio/eventlet loop.
"""

import io
import os
import time

# Real (non-green) threading â€” see module docstring re: monkey_patch ordering.
import threading as _native_threading
import queue as _native_queue

import cv2

# Capture the *native* sleep/time BEFORE eventlet.monkey_patch() runs in
# server_entry.py. The capture-worker threads are real OS threads, so they must
# block natively. The MJPEG generator, however, runs inside the eventlet reactor
# and must yield green (see _green_sleep below).
_native_sleep = time.sleep
_native_time = time.time
_native_monotonic = time.monotonic

try:
    import eventlet
    _green_sleep = getattr(eventlet, "sleep", None)
except Exception:  # pragma: no cover - eventlet always present in this build
    _green_sleep = None


def _sleep(seconds):
    """Sleep that works in BOTH eventlet and plain-Thread Flask modes.

    In the packaged app the server runs under eventlet (socketio.run), so we
    prefer ``eventlet.sleep`` to yield the green loop. But when the same module
    is exercised via a plain Flask ``app.run(threaded=True)`` (tests / dev), we
    must fall back to a real ``time.sleep`` so the generator keeps producing.

    We detect which environment we're in by trying to determine whether the
    calling thread is an eventlet greenlet. If it isn't, eventlet.sleep() would
    hang (no active hub), so we always fall back to native time.sleep unless we
    can confirm we're inside a live green thread.
    """
    if _green_sleep is not None and _in_greenthread():
        try:
            _green_sleep(seconds)
            return
        except Exception:
            pass
    _native_sleep(seconds)


def _in_greenthread():
    """True if the current thread is an eventlet green thread (active hub)."""
    if _green_sleep is None:
        return False
    try:
        import eventlet as _e
        if _e.getcurrent() is not None:
            return True
    except Exception:
        return False
    return False

try:
    import numpy as _np
except Exception:  # pragma: no cover - numpy ships with opencv-python
    _np = None


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
TARGET_FPS = 30.0
JPEG_QUALITY = 80
MAX_SOURCE_SCAN = 16
DSHOW_BACKENDS = (cv2.CAP_DSHOW, cv2.CAP_ANY)
PROBE_TIMEOUT = 3.0   # seconds to wait for a device to deliver a frame for probing
FRAME_TIMEOUT = 5.0   # seconds to wait for a device to deliver a frame for grab

_scan_lock = _native_threading.Lock()


def _read_frame(fn, timeout=3.0):
    """Run ``fn()`` in a background thread and wait up to ``timeout`` seconds.

    Some HDMI capture cards block forever in ``VideoCapture.read()`` when the
    source is offline or mid-switch, which would otherwise hang the whole
    eventlet request handler. Running the read in a (detached) native thread and
    giving up after a short deadline lets us drop the source and keep moving.
    """
    box = []

    def _worker():
        try:
            box.append(fn())
        except Exception as e:  # noqa: BLE001 - collapse to None
            box.append(None)

    t = _native_threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        # Still stuck: abandon this thread (the OS will eventually reap the
        # blocked read), treat the source as unavailable right now.
        return None
    return box[0] if box else None


_probe_cache = {}  # index -> (w, h) once resolved; (0,0) means "no device here"
_probe_lock = _native_threading.Lock()


def _probe_resolution_cached(index):
    """Cached version of ``_probe_resolution``.

    Re-opening the *same* DSHOW device repeatedly (e.g. once every 5s from the
    console poller) can leave a prior camera locked and make the next
    ``VideoCapture()`` block forever, so we resolve each device exactly once and
    keep the measured resolution for the process lifetime.

    The ENTIRE probe (open + read + release) runs inside ``_read_frame``'s
    native thread, so an offline / mid-switch / busy device can never block the
    eventlet request handler.
    """
    from cv2 import VideoCapture, CAP_DSHOW, CAP_ANY  # noqa: F401
    with _probe_lock:
        if index in _probe_cache:
            return _probe_cache[index]

        def _job():
            cap = None
            try:
                for backend in (CAP_DSHOW, CAP_ANY):
                    try:
                        cap = VideoCapture(index, backend)
                    except Exception:
                        cap = None
                    if cap is not None and cap.isOpened():
                        break
                    if cap is not None:
                        cap.release()
                        cap = None
                if cap is None or not cap.isOpened():
                    return (0, 0)
                ok, frame = cap.read()
                if ok and frame is not None:
                    return (int(frame.shape[1]), int(frame.shape[0]))
                return (0, 0)
            finally:
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass

        res = _read_frame(_job, timeout=PROBE_TIMEOUT)
        _probe_cache[index] = res if res else (0, 0)
        return _probe_cache[index]


# --------------------------------------------------------------------------- #
# Single-source capture worker
# --------------------------------------------------------------------------- #
class _SourceWorker:
    """Owns one capture device and the latest JPEG frame for its subscribers."""

    def __init__(self, index, target_fps=TARGET_FPS, quality=JPEG_QUALITY):
        self.index = index
        self.target_fps = target_fps
        self.quality = quality
        self.frame_interval = 1.0 / max(1, target_fps)

        self._cap = None
        self._latest = None          # latest JPEG bytes (or None)
        self._mtime = 0.0
        self._lock = _native_threading.Lock()

        self._subscribers = 0
        self._sub_event = _native_threading.Event()
        self._stop = False
        self._thread = None

    # -- lifecycle ----------------------------------------------------------
    def add_subscriber(self):
        with self._lock:
            self._subscribers += 1
            self._sub_event.set()
        if self._thread is None or not self._thread.is_alive():
            self._start_thread()

    def remove_subscriber(self):
        with self._lock:
            self._subscribers = max(0, self._subscribers - 1)
            if self._subscribers == 0:
                self._sub_event.clear()

    @property
    def subscriber_count(self):
        return self._subscribers

    def _start_thread(self):
        self._stop = False
        self._thread = _native_threading.Thread(
            target=self._run, name=f"live-capture-{self.index}", daemon=True
        )
        self._thread.start()

    def shutdown(self):
        self._stop = True
        self._sub_event.set()

    # -- capture loop -------------------------------------------------------
    def _open(self):
        # DSHOW works reliably on Windows for camera / capture-card devices.
        # (CAP_ANY/MSMF can hang on some virtual/HDMI capture cards.)
        if hasattr(cv2, "CAP_DSHOW"):
            cap = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)
            if cap.isOpened():
                return cap
            cap.release()
        return cv2.VideoCapture(self.index)

    def _run(self):
        # Guarded open + warm-up: if the device is mid-switch, held by another
        # app, or simply offline, we bail out instead of blocking forever.
        self._cap = _read_frame(self._open, timeout=3.0)
        if self._cap is None or not self._cap.isOpened():
            with self._lock:
                self._latest = None
            self._sub_event.clear()
            self._sub_event.clear()
            return

        def _warmup():
            ok, frame = self._cap.read()
            if not ok or frame is None:
                return None
            ok_enc, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
            if not ok_enc:
                return None
            return buf.tobytes()

        first = _read_frame(_warmup, timeout=FRAME_TIMEOUT)
        if first:
            with self._lock:
                self._latest = first
                self._mtime = _native_monotonic()

        next_t = _native_monotonic()
        try:
            while not self._stop:
                have_subs = self._subscribers > 0
                if not have_subs:
                    # No clients: release the handle and idle until the next one.
                    self._sub_event.wait(timeout=0.2)
                    self._sub_event.clear()
                    continue

                if self._cap is None or not self._cap.isOpened():
                    self._cap = _read_frame(self._open, timeout=3.0)
                    if self._cap is None or not self._cap.isOpened():
                        _native_sleep(0.3)
                        continue

                ok, frame = self._cap.read()
                now = _native_monotonic()
                if not ok or frame is None:
                    # Device dropped: try to reopen, then rest.
                    with self._lock:
                        self._latest = None
                    if self._cap is not None:
                        self._cap.release()
                    self._cap = None
                    _native_sleep(0.5)
                    continue

                ok_enc, buf = cv2.imencode(
                    ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.quality]
                )
                if ok_enc:
                    with self._lock:
                        self._latest = buf.tobytes()
                        self._mtime = now

                # Keep cadence near target_fps without busy-waiting.
                next_t = max(next_t + self.frame_interval, now)
                sleep_for = next_t - _native_monotonic()
                if sleep_for > 0:
                    _native_sleep(sleep_for)
        finally:
            with self._lock:
                self._latest = None
            if self._cap is not None:
                self._cap.release()
                self._cap = None

    # -- reader -------------------------------------------------------------
    def snapshot(self):
        """Return (bytes, mtime) of the latest JPEG frame, or (None, 0)."""
        with self._lock:
            return self._latest, self._mtime

    def probe(self, timeout=1.0):
        """Open the device and grab one frame; returns (w, h) or (0, 0)."""
        cap = self._open()
        try:
            if cap is None or not cap.isOpened():
                return (0, 0)
            ok, frame = cap.read()
            if ok and frame is not None:
                return (int(frame.shape[1]), int(frame.shape[0]))
            return (0, 0)
        finally:
            cap.release()


# --------------------------------------------------------------------------- #
# Source registry + MJPEG generator
# --------------------------------------------------------------------------- #
_registry = {}
_registry_lock = _native_threading.Lock()


def _get_worker(index):
    with _registry_lock:
        w = _registry.get(index)
        if w is None:
            w = _SourceWorker(index)
            _registry[index] = w
        return w


def describe_sources(scan=MAX_SOURCE_SCAN, rescan=False):
    """Enumerate server-side capture devices. Returns a list of dicts.

    Uses a lightweight, direct cv2 probe per index (not the worker registry) so
    this doesn't leave half-initialised capture threads around. Each index is
    opened once, a single frame is read, and the handle is closed immediately â€”
    this keeps DirectShow happy and avoids disrupting subsequent MJPEG streams.

    ``rescan=True`` clears the per-index probe cache first so a device plugged
    in *after* the first scan (e.g. a USB webcam / USB HDMI capture card) is
    discovered instead of being masked by a stale "no device here" result.
    """
    if rescan:
        _invalidate_probe_cache()
    names = _dshow_device_names()
    out = []
    for i in range(scan):
        w, h = _probe_resolution(i)
        if w and h:
            name = names[i] if 0 <= i < len(names) else None
            out.append({"index": i, "w": w, "h": h, "name": name})
    return out


def _invalidate_probe_cache():
    """Forget resolution probes so a fresh scan sees newly-plugged devices."""
    with _probe_lock:
        _probe_cache.clear()


_dshow_names = None
_dshow_names_lock = _native_threading.Lock()


def _dshow_device_names():
    """DirectShow disTransaction names in enumerator order, or [] when unavailable.

    cv2's DSHOW indices come from the SAME system video-input enumerator as
    DirectShow, so ``names[i]`` corresponds to source index ``i``. This lets the
    operator pick a USB webcam / USB HDMI capture card by *name* instead of a
    blind number. The list is resolved lazily (the PyGrabber/comtypes import is
    guarded so the module still works in environments without it) and cached.
    """
    global _dshow_names
    if _dshow_names is None:
        with _dshow_names_lock:
            if _dshow_names is None:
                try:
                    from pygrabber.dshow_graph import FilterGraph
                    _dshow_names = _read_frame(
                        FilterGraph().get_input_devices, timeout=5.0
                    ) or []
                except Exception:
                    _dshow_names = []
    return list(_dshow_names)


def _probe_resolution(index):
    """Open `index` once and return (width, height), or (0, 0).

    Uses a cached, timeout-guarded probe so a capture card that blocks in
    ``VideoCapture.read()`` (offline / mid-switch) cannot hang the request
    handler; see ``_read_frame`` / ``_probe_resolution_cached``.
    """
    return _probe_resolution_cached(index)


def _drop_unused(index):
    """Remove a worker only if it has no subscribers (post-probe cleanup)."""
    with _registry_lock:
        w = _registry.get(index)
        if w is not None and w.subscriber_count == 0:
            w.shutdown()
            _registry.pop(index, None)


def snapshot(index):
    """Latest JPEG bytes for a source (without creating a worker if absent)."""
    with _registry_lock:
        w = _registry.get(index)
    if w is None:
        return None
    return w.snapshot()[0]


def worker_mjpeg(index, boundary=b"--frame"):
    """Yield MJPEG multipart chunks for a live source â€” via the SHARED slot.

    The device handle is owned ONLY by the per-source capture worker (a native
    thread). This generator just polls the worker's latest JPEG, so it NEVER
    opens the camera inside the request handler. That is what makes it safe to
    have several consumers (projection ch1 + the operator's mirror iframe)
    watching the same source at once: DirectShow video devices allow only ONE
    open handle, and a second open would block the server.

    When the worker has no frame yet (device opening / busy), the stream simply
    waits and emits nothing; the client keeps its last frame instead of the
    request handler hanging.
    """
    w = _get_worker(index)
    w.add_subscriber()
    try:
        last_id = 0
        while True:
            data, mtime = w.snapshot()
            if data is not None and mtime != last_id:
                last_id = mtime
                header = (
                    f"Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(data)}\r\n\r\n"
                ).encode("latin-1")
                yield boundary + b"\r\n" + header + data + b"\r\n"
            _sleep(1.0 / max(1, TARGET_FPS))
    finally:
        w.remove_subscriber()


# --------------------------------------------------------------------------- #
# Flask wiring
# --------------------------------------------------------------------------- #
def init_app(app):
    """Register the Live Input Flask routes on the existing app.

    Called from server_entry.py AFTER ``from app import app``. The recovered
    app.pyc is untouched â€” these endpoints are additive.
    """
    from flask import Response, jsonify
    from flask_socketio import emit, disconnect as _sio_disconnect
    from flask import session

    # After ANY projection-aspect is saved, rebroadcast the new aspect to EVERY
    # channel room so every open output window (operator monitor + separate
    # projectors/TVs) updates live â€” even channels that weren't the one edited.
    # The original app.pyc only broadcasts to the edited channel's own room, so
    # other displays would stay stale until a manual refresh.
    try:
        from app import socketio as _app_socketio
        from flask import request as _flask_request
        _registered_channels = ("ch1", "ch2", "ch3", "ch4", "ch5")

        @app.after_request
        def _broadcast_aspect_after_save(resp):
            # Only react to a successful aspect-save POST â€” never touch streamed
            # responses (MJPEG etc.). This avoids consuming the response stream.
            try:
                if resp.status_code == 200 and _flask_request.method == "POST" \
                        and _flask_request.path.rstrip("/").endswith("/projection") \
                        and session.get("operator"):
                    _app_socketio.emit("aspect:update",
                                       {"aspect": (_flask_request.get_json(silent=True) or {}).get("projection_aspect", "off")},
                                       room="console")
                    for _ch in _registered_channels:
                        _app_socketio.emit("aspect:update",
                                           {"aspect": (_flask_request.get_json(silent=True) or {}).get("projection_aspect", "off")},
                                           room=_ch)
            except Exception:
                pass
            return resp
    except Exception:
        pass

    # Broadcast a manual layer toggle (from the operator's monitor rail) to every
    # main channel room, so hiding/showing a layer on the monitor immediately
    # applies to all projection screens (and the operator monitor mirrors it).
    try:
        from app import socketio as _sio_layer
        _layer_channels = ("ch1", "ch2", "ch3", "ch4", "ch5")

        @_sio_layer.on("layer:set")
        def _on_layer_set(data):
            try:
                ldata = data if isinstance(data, dict) else {}
                layer = ldata.get("layer")
                show  = bool(ldata.get("show", True))
                if layer:
                    for _ch in _layer_channels:
                        _sio_layer.emit("layer:set", {"layer": layer, "show": show}, room=_ch)
            except Exception:
                pass
    except Exception:
        pass

    @app.route("/api/live/sources", methods=["GET"])
    def _api_live_sources():
        from flask import request as _req
        rescan = bool(_req.args.get("rescan", ""))
        # A rescanned enumeration re-probes EVERY device index + enumerates
        # DirectShow, which can take many seconds (especially with an offline or
        # busy capture card). Running the whole call on a detatched native thread
        # with a deadline means the eventlet hub never blocks on it; if it doesn't
        # finish in time we fall back to the already-cached list rather than hang.
        if rescan:
            def _job():
                return describe_sources(rescan=True)
            fresh = _read_frame(_job, timeout=FRAME_TIMEOUT + 3.0)
            if fresh is None:
                fresh = describe_sources(rescan=False)
            return jsonify({"sources": fresh})
        return jsonify({"sources": describe_sources(rescan=False)})

    @app.route("/live/feed/<int:index>.mjpeg", methods=["GET"])
    def _live_feed(index):
        # Serve the MJPEG stream from the DEDICATED sidecar server (native
        # threads on its own port) via a finite 308 redirect. The main Flask /
        # eventlet loop never carries an infinite stream, so it can never hang.
        from flask import redirect
        return redirect("http://127.0.0.1:%d/live/feed/%d.mjpeg" % (stream_port(), index), code=308)

    @app.route("/live/snapshot/<int:index>.jpg", methods=["GET"])
    def _live_snapshot(index):
        # Prefer the worker's shared slot (zero device opens here); fall back to
        # a guarded one-shot grab only if the worker never produced a frame.
        with _registry_lock:
            w = _registry.get(index)
        data = w.snapshot()[0] if w is not None else None
        if data is None:
            data = grab_frame(index)
        if data is None:
            return jsonify({"status": "no frame"}), 204
        return _send_bytes(data, "image/jpeg")

    return app


def grab_frame(index):
    """Open `index` once, read one frame, JPEG-encode it. Returns bytes or None.

    The WHOLE job (open + read + encode + release) runs inside ``_read_frame``'s
    native thread with a deadline, so an offline / mid-switch / busy capture
    device cannot hang the eventlet request handler.
    """
    def _job():
        cap = None
        try:
            try:
                if hasattr(cv2, "CAP_DSHOW"):
                    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
                if cap is None or not cap.isOpened():
                    if cap is not None:
                        cap.release()
                    cap = cv2.VideoCapture(index)
                if cap is None or not cap.isOpened():
                    return None
                ok, frame = cap.read()
                if not ok or frame is None:
                    return None
                ok_enc, buf = cv2.imencode(
                    ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
                )
                if not ok_enc:
                    return None
                return buf.tobytes()
            finally:
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass
        except Exception:
            return None

    return _read_frame(_job, timeout=FRAME_TIMEOUT)


# --------------------------------------------------------------------------- #
# Sidecar live stream server (native threads, AWAY from eventlet/socketio)
# --------------------------------------------------------------------------- #
# Serving an infinite MJPEG stream from the eventlet/socketio WSGI loop can hang
# the whole server (it has done so repeatedly). So live video is served by a
# tiny, dedicated HTTP server on its OWN port using REAL OS threads and REAL
# sockets (never monkey-patched). The main Flask routes below only return a
# finite redirect/status, so they can never block the green loop.

STREAM_HOST = "0.0.0.0"
STREAM_PORT = int(os.environ.get("LEITURGIA_STREAM_PORT", "5002"))

_stream_port = [STREAM_PORT]


def stream_port():
    return _stream_port[0]


def _mjpeg_generator(index):
    """Native generator yielding MJPEG frames from the shared worker slot."""
    w = _get_worker(index)
    w.add_subscriber()
    try:
        last_id = 0
        while True:
            data, mtime = w.snapshot()
            if data is not None and mtime != last_id:
                last_id = mtime
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: %d\r\n\r\n%s\r\n" % (len(data), data)
                )
            try:
                _native_sleep(1.0 / max(1, TARGET_FPS))
            except Exception:
                break
    finally:
        w.remove_subscriber()


def start_stream_server():
    """Start the dedicated live-stream HTTP server in a detached native thread.

    Returns the bound port (None if every candidate port is taken). Uses real
    (unpatched) sockets + ThreadingHTTPServer, completely isolated from the
    eventlet green loop powering the main Flask app — so an infinite MJPEG
    stream can never hang the operator/projection server.
    """
    global _stream_port
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class _H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_GET(self):
            idx = None
            seg = (self.path.split("?", 1)[0] if "?" in self.path else self.path)
            seg = seg.strip("/")
            if "." in seg:
                seg = seg.split(".")[0]
            if "/" in seg:
                seg = seg.split("/")[-1]
            try:
                idx = int(seg)
            except Exception:
                idx = None
            if idx is None:
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
                for chunk in _mjpeg_generator(idx):
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
    for _try_port in (_stream_port[0], _stream_port[0] + 1, _stream_port[0] + 2):
        try:
            sock = _Server(("0.0.0.0", _try_port), _H)
            _stream_port[0] = _try_port
            break
        except OSError:
            continue
    if sock is None:
        return None
    t = threading.Thread(target=sock.serve_forever, daemon=True, name="live-stream")
    t.start()
    return _stream_port[0]


def _send_bytes(data, mimetype):
    """Return a small in-memory binary response."""
    import io as _io
    buf = _io.BytesIO(data)
    from flask import send_file
    return send_file(
        buf,
        mimetype=mimetype,
        as_attachment=False,
        download_name="frame.jpg",
        conditional=True,
    )

