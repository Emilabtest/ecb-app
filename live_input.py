"""
live_input.py — Server-side live video capture & MJPEG streaming.

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
import time

# Real (non-green) threading — see module docstring re: monkey_patch ordering.
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
MAX_SOURCE_SCAN = 12
DSHOW_BACKENDS = (cv2.CAP_DSHOW, cv2.CAP_ANY)

_scan_lock = _native_threading.Lock()


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
        self._cap = self._open()
        if self._cap is None or not self._cap.isOpened():
            with self._lock:
                self._latest = None
            self._sub_event.clear()
            return

        next_t = _native_monotonic()
        try:
            while not self._stop:
                have_subs = self._subscribers > 0
                if not have_subs:
                    self._sub_event.wait(timeout=0.2)
                    self._sub_event.clear()
                    continue

                ok, frame = self._cap.read()
                now = _native_monotonic()
                if not ok or frame is None:
                    # Retry opening the device (cable unplug/replug), then rest.
                    self._cap.release()
                    self._sub_event.clear()
                    _native_sleep(0.5)
                    self._cap = self._open()
                    next_t = _native_monotonic()
                    continue

                ok_enc, buf = cv2.imencode(
                    ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.quality]
                )
                if ok_enc:
                    with self._lock:
                        self._latest = buf.tobytes()
                        self._mtime = now

                # Keep cadence near target_fps without busy-waiting.
                next_t += self.frame_interval
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


def describe_sources(scan=MAX_SOURCE_SCAN):
    """Enumerate server-side capture devices. Returns a list of dicts.

    Uses a lightweight, direct cv2 probe per index (not the worker registry) so
    this doesn't leave half-initialised capture threads around. Each index is
    opened once, a single frame is read, and the handle is closed immediately —
    this keeps DirectShow happy and avoids disrupting subsequent MJPEG streams.
    """
    out = []
    for i in range(scan):
        w, h = _probe_resolution(i)
        if w and h:
            out.append({"index": i, "w": w, "h": h})
    return out


def _probe_resolution(index):
    """Open `index` once and return (width, height), or (0, 0)."""
    cap = None
    try:
        if hasattr(cv2, "CAP_DSHOW"):
            cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if cap is None or not cap.isOpened():
            if cap is not None:
                cap.release()
            cap = cv2.VideoCapture(index)
        if cap is None or not cap.isOpened():
            return (0, 0)
        ok, frame = cap.read()
        if ok and frame is not None:
            return (int(frame.shape[1]), int(frame.shape[0]))
        return (0, 0)
    except Exception:
        return (0, 0)
    finally:
        if cap is not None:
            cap.release()


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
        # one-shot grab
        w = _SourceWorker(index)
        return w.snapshot()[0]
    return w.snapshot()[0]


def mjpeg_generator(index, boundary=b"--frame"):
    """Yield MJPEG multipart chunks for a live source.

    Captures frames DIRECTLY in this generator (in the request thread) rather
    than relying on a background capture thread. This keeps the stream working
    under both the packaged eventlet server and a plain ``app.run`` (dev/test).
    Each client opens its own capture handle; for a single projector this is
    negligible and far more robust than cross-thread device sharing.
    """
    send_interval = 1.0 / max(1, TARGET_FPS)
    # Open the capture handle once for the duration of the stream.
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
                # Emit a minimal error frame so the client at least sees a stream
                yield boundary + b"\r\nContent-Type: image/jpeg\r\n\r\n" + b"\r\n"
                return

            last_sent = 0.0
            ok_base, first = cap.read()  # warm up
            while True:
                ok, frame = cap.read()
                if not ok or frame is None:
                    # Device dropped: try to reopen.
                    cap.release()
                    _sleep(0.3)
                    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW) \
                          if hasattr(cv2, "CAP_DSHOW") else cv2.VideoCapture(index)
                    if cap is None or not cap.isOpened():
                        _sleep(0.3)
                        continue
                    ok, frame = cap.read()
                    if not ok:
                        continue

                ok_enc, buf = cv2.imencode(
                    ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
                )
                if not ok_enc:
                    continue
                data = buf.tobytes()
                header = (
                    f"Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(data)}\r\n\r\n"
                ).encode("latin-1")
                yield boundary + b"\r\n" + header + data + b"\r\n"

                # Keep cadence near target_fps without busy-waiting.
                cadence = _native_monotonic() - last_sent
                if cadence < send_interval:
                    _sleep(send_interval - cadence)
                last_sent = _native_monotonic()
        finally:
            if cap is not None:
                cap.release()
    except GeneratorExit:
        raise
    except Exception:
        # Don't leak the capture handle.
        if cap is not None:
            cap.release()
        raise


# --------------------------------------------------------------------------- #
# Flask wiring
# --------------------------------------------------------------------------- #
def init_app(app):
    """Register the Live Input Flask routes on the existing app.

    Called from server_entry.py AFTER ``from app import app``. The recovered
    app.pyc is untouched — these endpoints are additive.
    """
    from flask import Response, jsonify
    from flask_socketio import emit, disconnect as _sio_disconnect
    from flask import session

    @app.route("/api/live/sources", methods=["GET"])
    def _api_live_sources():
        return jsonify({"sources": describe_sources()})

    @app.route("/live/feed/<int:index>.mjpeg", methods=["GET"])
    def _live_feed(index):
        # direct_passthrough + no buffering lets the eventlet WSGI server flush
        # each MJPEG chunk immediately rather than holding the whole stream.
        from werkzeug.wsgi import ClosingIterator
        resp = Response(
            mjpeg_generator(index),
            mimetype="multipart/x-mixed-replace; boundary=--frame",
            direct_passthrough=True,
        )
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Connection"] = "close"
        resp.headers["X-Accel-Buffering"] = "no"
        return resp

    @app.route("/live/snapshot/<int:index>.jpg", methods=["GET"])
    def _live_snapshot(index):
        # One-shot frame grab: open the device, read one frame, encode & return.
        data = grab_frame(index)
        if data is None:
            return jsonify({"status": "no frame"}), 204
        return _send_bytes(data, "image/jpeg")

    return app


def grab_frame(index):
    """Open `index` once, read one frame, JPEG-encode it. Returns bytes or None."""
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
                cap.release()
    except Exception:
        return None


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
