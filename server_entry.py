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

# Register the server-side Live Input endpoints (additive; app.pyc untouched).
live_input.init_app(app)


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
