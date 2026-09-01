"""
live_input.py — Server-side live video capture & MJPEG streaming.

The original app.pyc only relays a *device_id* string to the projection clients,
and each projection.html browser then opened ``getUserMedia`` against its *own*
capture hardware. That breaks when the HDMI capture cards / webcams are plugged
into the *server* machine (the operator's PC), because the projection clients
(browsers on the projectors / LED wall) never see those devices.

This module solves that by capturing frames ON the server (where the capture
cards physically are) and relaying them to any client via MJPEG-over-HTTP.

It also hosts the **ECB CAST** wireless screen-share: a presenter opens ``/share``
in their browser, the browser captures their screen, and streams JPEG frames to
this server over Socket.IO. The server stores the latest frame per presenter and
serves it as another live source (``?cast=<id>``) through the same MJPEG path.

It is deliberately written OUTSIDE the recovered app.pyc so the sourceless
module stays untouched. Wiring happens in server_entry.py / the operator
console (index.html) / the projection template (projection.html).

SOURCE IDs
----------
A live source is identified by a string ``source_id``:
  * ``"<digit>"``            -> a server-side camera / HDMI capture card
  * ``"cast-<token>"``       -> a wireless ECB CAST presenter session

``describe_sources()`` merges both kinds so the operator console sees one list.
"""

import time
import uuid

# Real (non-green) threading — see module docstring re: monkey_patch ordering.
import threading as _native_threading

import cv2

# Capture the *native* sleep/time BEFORE eventlet.monkey_patch() runs in
# server_entry.py. The capture-worker threads are real OS threads, so they must
# block natively. The MJPEG generator, however, runs inside the eventlet reactor
# and must yield green (see _green_sleep below).
_native_sleep = time.sleep
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


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
TARGET_FPS = 30.0
JPEG_QUALITY = 80
MAX_SOURCE_SCAN = 12
CAST_NAME = "ECB CAST"
CAST_IDLE_TIMEOUT = 30.0  # drop a presenter after this long without a frame


# --------------------------------------------------------------------------- #
# Camera (capture-card) helpers
# --------------------------------------------------------------------------- #
def _probe_resolution(index):
    """Open capture `index` once and return (width, height), or (0, 0)."""
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


def grab_frame(index):
    """Open camera `index` once, read one frame, JPEG-encode it. bytes | None."""
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


# --------------------------------------------------------------------------- #
# ECB CAST source registry (wireless presenters)
# --------------------------------------------------------------------------- #
_cast_lock = _native_threading.Lock()
_cast_next = 0
_cast_sources = {}  # source_id -> {"name","jpeg","w","h","last"}


def _new_cast_token():
    global _cast_next
    with _cast_lock:
        _cast_next += 1
        return "c%02d" % _cast_next


def register_cast_source(name=CAST_NAME, w=0, h=0):
    """Register a wireless presenter and return its source_id."""
    source_id = "cast-%s" % _new_cast_token()
    with _cast_lock:
        _cast_sources[source_id] = {
            "name": name,
            "jpeg": None,
            "w": int(w or 0),
            "h": int(h or 0),
            "last": time.time(),
        }
    return source_id


def update_cast_source(source_id, jpeg_bytes, w=0, h=0):
    """Store the latest JPEG frame from a presenter (called on share:frame)."""
    if source_id not in _cast_sources:
        return
    with _cast_lock:
        src = _cast_sources[source_id]
        src["jpeg"] = jpeg_bytes
        if w:
            src["w"] = int(w)
        if h:
            src["h"] = int(h)
        src["last"] = time.time()


def drop_cast_source(source_id):
    """Remove a presenter's source (on disconnect / idle)."""
    with _cast_lock:
        _cast_sources.pop(source_id, None)


def cast_sources():
    """Return the list of currently-registered ECB CAST sources (drop idle)."""
    now = time.time()
    live = []
    stale = []
    with _cast_lock:
        for sid, s in _cast_sources.items():
            if now - s["last"] > CAST_IDLE_TIMEOUT:
                stale.append(sid)
            elif s["jpeg"] is not None:
                live.append((sid, s))
        if stale:
            for sid in stale:
                _cast_sources.pop(sid, None)
    return live


def cast_snapshot(source_id):
    """Latest JPEG bytes for a cast source; bytes | None."""
    with _cast_lock:
        s = _cast_sources.get(source_id)
        if s and s["jpeg"] is not None:
            return s["jpeg"]
    return None


# --------------------------------------------------------------------------- #
# Merged source listing
# --------------------------------------------------------------------------- #
def describe_sources(scan=MAX_SOURCE_SCAN):
    """Enumerate server-side cameras + current ECB CAST presenters.

    Returns a list of dicts, each with ``source_id`` (string), ``name``,
    ``w``/``h``, and ``kind`` ("camera" or "cast").
    """
    out = []
    for i in range(scan):
        w, h = _probe_resolution(i)
        if w and h:
            out.append(
                {
                    "source_id": str(i),
                    "index": i,
                    "name": "Camera %d (%dx%d)" % (i, w, h),
                    "w": w,
                    "h": h,
                    "kind": "camera",
                }
            )
    for sid, s in cast_sources():
        out.append(
            {
                "source_id": sid,
                "name": "%s (%dx%d)" % (s["name"], s.get("w", 0), s.get("h", 0)),
                "w": s.get("w", 0),
                "h": s.get("h", 0),
                "kind": "cast",
            }
        )
    return out


def is_cast_source(source_id):
    return isinstance(source_id, str) and source_id.startswith("cast-")


def _cast_index_of(source_id):
    """Return the numeric part of a cast source_id, or None."""
    if source_id.startswith("cast-"):
        return source_id[len("cast-"):]
    return None


# --------------------------------------------------------------------------- #
# MJPEG generators
# --------------------------------------------------------------------------- #
def _camera_mjpeg_generator(index, boundary=b"--frame"):
    """Yield MJPEG chunks for a server-side camera / capture card.

    Captures frames DIRECTLY in this generator (in the request thread) rather
    than relying on a background capture thread. This keeps the stream working
    under both the packaged eventlet server and a plain ``app.run`` (dev/test).
    Each client opens its own capture handle; for a single projector this is
    negligible and far more robust than cross-thread device sharing.
    """
    send_interval = 1.0 / max(1, TARGET_FPS)
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
                yield boundary + b"\r\nContent-Type: image/jpeg\r\n\r\n" + b"\r\n"
                return

            last_sent = 0.0
            while True:
                ok, frame = cap.read()
                if not ok or frame is None:
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
        if cap is not None:
            cap.release()
        raise


def _cast_mjpeg_generator(source_id, boundary=b"--frame"):
    """Yield MJPEG chunks for a wireless ECB CAST presenter.

    Each frame is the latest JPEG the presenter pushed via Socket.IO. The
    generator only sends a chunk when a *new* frame appears, so a still screen
    does not spam the network while staying live.
    """
    send_interval = 1.0 / max(1, TARGET_FPS)
    last_mtime = -1.0
    last_sent = 0.0
    try:
        while True:
            with _cast_lock:
                s = _cast_sources.get(source_id)
                jpeg = s["jpeg"] if s else None
                mtime = s["last"] if s else 0.0
            if jpeg is None:
                _sleep(0.2)
                continue
            if mtime != last_mtime:
                last_mtime = mtime
                header = (
                    f"Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(jpeg)}\r\n\r\n"
                ).encode("latin-1")
                yield boundary + b"\r\n" + header + jpeg + b"\r\n"
                last_sent = _native_monotonic()
            else:
                _sleep(0.05)
            cadence = _native_monotonic() - last_sent
            if cadence < send_interval:
                _sleep(send_interval - cadence)
    except GeneratorExit:
        raise


def mjpeg_generator(source_id, boundary=b"--frame"):
    """Dispatch MJPEG generation to the camera or cast path by source_id."""
    if is_cast_source(source_id):
        return _cast_mjpeg_generator(source_id, boundary)
    try:
        return _camera_mjpeg_generator(int(source_id), boundary)
    except (TypeError, ValueError):
        return _cast_mjpeg_generator(source_id, boundary)


# --------------------------------------------------------------------------- #
# Flask + Socket.IO wiring
# --------------------------------------------------------------------------- #
def init_app(app, socketio=None):
    """Register the Live Input Flask routes + the ECB CAST socket events.

    Called from server_entry.py AFTER ``from app import app`` (and socketio).
    The recovered app.pyc is untouched — these endpoints are additive.
    """
    from flask import Response, jsonify, render_template, request

    @app.route("/api/live/sources", methods=["GET"])
    def _api_live_sources():
        return jsonify({"sources": describe_sources()})

    @app.route("/live/feed/<path:source_id>.mjpeg", methods=["GET"])
    def _live_feed(source_id):
        resp = Response(
            mjpeg_generator(source_id),
            mimetype="multipart/x-mixed-replace; boundary=--frame",
            direct_passthrough=True,
        )
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Connection"] = "close"
        resp.headers["X-Accel-Buffering"] = "no"
        return resp

    @app.route("/live/snapshot/<path:source_id>.jpg", methods=["GET"])
    def _live_snapshot(source_id):
        if is_cast_source(source_id):
            data = cast_snapshot(source_id)
        else:
            data = grab_frame(int(source_id))
        if data is None:
            return jsonify({"status": "no frame"}), 204
        return _send_bytes(data, "image/jpeg")

    @app.route("/share", methods=["GET"])
    def _share_page():
        return render_template("share.html", cast_name=CAST_NAME)

    # -- ECB CAST socket events ----------------------------------------------
    def _share_register(data):
        """Presenter opens /share and registers; return its source_id."""
        name = (data or {}).get("name") or CAST_NAME
        w = (data or {}).get("w") or 0
        h = (data or {}).get("h") or 0
        sid = register_cast_source(name, w, h)
        if socketio is not None:
            from flask_socketio import join_room
            room = "cast-" + sid
            join_room(room)
        # tell the operator console the source list changed
        if socketio is not None:
            emit("live:sources", {"sources": describe_sources()}, broadcast=True)
        return {"source_id": sid, "name": name}

    def _share_frame(data):
        """Presenter pushes a base64/raw JPEG frame for its session."""
        sid = (data or {}).get("source_id")
        if not sid:
            return
        frame_b64 = (data or {}).get("frame")
        if not frame_b64:
            return
        try:
            import base64
            raw = base64.b64decode(frame_b64)
        except Exception:
            return
        update_cast_source(sid, raw, (data or {}).get("w"), (data or {}).get("h"))

    def _share_close(data):
        sid = (data or {}).get("source_id")
        if sid:
            drop_cast_source(sid)
        if socketio is not None:
            emit("live:sources", {"sources": describe_sources()}, broadcast=True)

    def _share_disconnect():
        # Clean up any cast source tied to this connection.
        from flask_socketio import request as sio_request
        sid = getattr(sio_request, "_cast_source_id", None)
        if sid:
            drop_cast_source(sid)
        if socketio is not None:
            emit("live:sources", {"sources": describe_sources()}, broadcast=True)

    if socketio is not None:

        @socketio.on("share:register", namespace="/share")
        def _on_share_register(data):
            return _share_register(data)

        @socketio.on("share:frame", namespace="/share")
        def _on_share_frame(data):
            _share_frame(data)

        @socketio.on("share:close", namespace="/share")
        def _on_share_close(data):
            _share_close(data)

        @socketio.on("disconnect")
        def _on_share_disconnect():
            _share_disconnect()

    return app


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
