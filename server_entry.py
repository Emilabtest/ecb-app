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
else:
    HERE = os.path.dirname(os.path.abspath(__file__))

os.chdir(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from licensing import verify_licence

_lic_ok, _lic_reason = verify_licence()
if not _lic_ok:
    os.makedirs('data', exist_ok=True)
    with open(os.path.join('data', 'license_error.log'), 'w') as f:
        f.write('Leiturgia is locked to a specific machine.\n')
        f.write('Reason: %s\n' % _lic_reason)
        f.write('This copy is not licensed for this PC. Contact the owner.\n')
    sys.exit(1)

import eventlet
eventlet.monkey_patch()

from app import app, socketio


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
    socketio.run(app, host='0.0.0.0', port=5001, debug=False)
