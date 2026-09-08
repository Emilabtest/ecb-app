"""stream_server.py — dedicated live-video stream daemon (child process).

The main LeiturgiaServer.exe boots with the full Flask/socketio/eventlet stack.
A long-lived OpenCV capture loop living in the SAME process as the eventlet hub
has repeatedly deadlocked the hub (frozen all HTTP). So live capture runs here,
in a SEPARATE process with NO Flask, NO socketio, NO eventlet monkey-patch:
just real threads + a tiny HTTP server answering:

    GET /live/feed/<index>.mjpeg   → infinite MJPEG from the shared worker slot
    GET /live/snapshot/<index>.jpg → one JPEG frame

The main server is launched again by booting the same exe with ``--stream``.
"""

import sys
import threading


def main():
    import live_input

    port = live_input.start_stream_server()
    if port is None:
        sys.stderr.write("stream: no free port\n")
        sys.exit(1)
    sys.stdout.write("stream ready on port %d\n" % port)
    sys.stdout.flush()

    # Block forever; the http server runs its own daemon thread.
    ev = threading.Event()
    ev.wait()


if __name__ == "__main__":
    main()