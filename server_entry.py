"""
server_entry.py — Runs the Leiturgia Flask server as the main entry point.

Used as the PyInstaller entry point for the embedded server executable. Changes
the working directory to this file's folder so runtime state (config.json,
data/, media/, output/) resolves correctly regardless of where the app is
launched from.
"""
import os
import sys
import glob

if getattr(sys, 'frozen', False):
    # The windowed build has no attached console: sys.stdout / sys.stderr are
    # None, and the first logging emit (basicConfig uses stderr, flushed on
    # every record) crashes with "'NoneType' object has no attribute 'flush'".
    # Give them silent StringIO sinks so every launch path (operator app,
    # direct/console launch, dev) behaves identically instead of crashing.
    import io as _io
    if sys.stdout is None:
        sys.stdout = _io.StringIO()
    if sys.stderr is None:
        sys.stderr = _io.StringIO()

if getattr(sys, 'frozen', False):
    HERE = os.path.dirname(sys.executable)
    _MEIPASS = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
    _MEIPASS = HERE

os.chdir(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _resolve(name):
    """Return the first existing path under the install dir or the PyInstaller
    _MEIPASS bundle dir, so recovery data resolves in both onefile and onedir."""
    cands = [os.path.join(HERE, name)]
    if _MEIPASS and _MEIPASS != HERE:
        cands.append(os.path.join(_MEIPASS, name))
    for c in cands:
        if os.path.exists(c):
            return c
    return cands[0]


def _register_pymod():
    """Expose the recovered .pyc project modules (app, roles, ...) on sys.path."""
    pymod = _resolve('pymod')
    if pymod and os.path.isdir(pymod):
        sys.path.insert(0, pymod)


_register_pymod()

# Dedicated live-video stream daemon mode.
#
# The main server boots with Flask/socketio/eventlet. A long-lived OpenCV capture
# loop running IN THAT SAME eventlet process deadlocks the hub, so live capture
# runs in a SEPARATE process: the same exe re-launched with `--stream`. This
# branch must come BEFORE the licence check (the child is on the same machine)
# and before anything imports eventlet/socketio.
if '--stream' in sys.argv:
    import stream_server
    stream_server.main()
    sys.exit(0)


from licensing import verify_licence

_lic_ok, _lic_reason = verify_licence()
if not _lic_ok:
    os.makedirs('data', exist_ok=True)
    with open(os.path.join('data', 'license_error.log'), 'w') as f:
        f.write('Leiturgia is locked to a specific machine.\n')
        f.write('Reason: %s\n' % _lic_reason)
        f.write('This copy is not licensed for this PC. Contact the owner.\n')
    sys.exit(1)

# Import live_input BEFORE eventlet.monkey_patch() so its capture threads bind
# to the real (non-green) threading/time modules. See live_input docstring.
import live_input

import eventlet
eventlet.monkey_patch()

from app import app, socketio


def _fix_asset_paths(app_obj):
    """Point Flask's template/static search paths at the real asset folders.

    The sourceless app module lives in ``pymod/``, so ``app.root_path`` resolves
    to ``<dir>/pymod`` and its default ``templates``/``static`` folders look in
    ``<dir>/pymod/templates`` (which does not exist). In the packaged build the
    assets are bundled at the top level (``HERE``/``_MEIPASS``), so override the
    Jinja searchpath and the static folder to point there. This keeps dev-mode
    and both onefile / onedir builds working.
    """
    tpl = _resolve('templates')
    sta = _resolve('static')
    if tpl and os.path.isdir(tpl):
        from flask import send_from_directory
        app_obj.jinja_loader.searchpath = [_MEIPASS or HERE, tpl]
        # Also keep the package-relative search path so pymod-relative refs work.
        if _MEIPASS and os.path.exists(os.path.join(_MEIPASS, tpl)):
            app_obj.jinja_loader.searchpath.append(os.path.join(_MEIPASS, tpl))
        app_obj.template_folder = tpl
    if sta and os.path.isdir(sta):
        app_obj.static_folder = sta


_fix_asset_paths(app)


class _NoStoreCache:
    """Force every response through no-store so operator/OED/remote pages are
    never served from the browser's stale cache after a redeploy. Without this,
    Flask sends no Cache-Control headers, browsers keep the old HTML heurist
    cached, and the app 'does not follow' edits until a manual hard refresh."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        def _start(status, headers, exc_info=None):
            hs = []
            for k, v in headers:
                if k.lower() == 'cache-control':
                    v = 'no-store, no-cache, must-revalidate, max-age=0'
                hs.append((k, v))
            if not any(k.lower() == 'cache-control' for k, _ in hs):
                hs.append(('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0'))
            return start_response(status, hs, exc_info)

        return self.wsgi_app(environ, _start)


app.wsgi_app = _NoStoreCache(app.wsgi_app)

# Register the server-side Live Input endpoints (additive; app.pyc untouched).
live_input.init_app(app)


def _spawn_stream_child():
    """Launch the dedicated live-stream daemon as a SEPARATE process.

    Live capture can deadlock the eventlet hub when it shares the main process.
    A child process (the same exe re-run with ``--stream``) isolates OpenCV on
    its own native threads + ports, so the operator/projection server can never
    freeze. Best-effort: if the spawn fails, streaming stays unavailable but the
    main server is unaffected.
    """
    import subprocess
    try:
        if getattr(sys, 'frozen', False):
            cmd = [sys.executable, '--stream']
            cwd = os.path.dirname(sys.executable)
        else:
            here = os.path.dirname(os.path.abspath(__file__))
            cmd = [sys.executable, '-m', 'stream_server', '--stream']
            cwd = here
        flag = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        subprocess.Popen(cmd, cwd=cwd, creationflags=flag)
    except Exception:
        pass


_spawn_stream_child()

# Register the build-id endpoint + HTML stamping so long-open output/operator
# tabs auto-reload as soon as a new build is deployed (additive; app.pyc
# untouched). Must run after live_input so the version middleware wraps last.
import server_version
server_version.init_app(app, inject=True)


def _ensure_dirs():
    for p in ('data', 'data/update', 'data/lyrics', 'output', 'media/images', 'media/videos'):
        os.makedirs(p, exist_ok=True)


def _clean_tmp():
    for _p in glob.glob(os.path.join('data', '.tmp-*.json')):
        try:
            os.unlink(_p)
        except OSError:
            continue


if __name__ == '__main__':
    _ensure_dirs()
    _clean_tmp()
    # Allow an alternate port (LEITURGIA_PORT) for dev/test without clobbering
    # the live server on 5001.
    import os as _os
    _port = int(_os.environ.get('LEITURGIA_PORT', '5001'))
    socketio.run(app, host='0.0.0.0', port=_port, debug=False)
