# Source Generated with Decompyle++
# File: version.pyc (Python 3.12)

import os
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_cached_version = None

def get_version():
    """Return the app version.

    Reads an embedded 'app.version' file (packaged as data alongside the exe),
    falling back to 'git describe' only in a development checkout. This works
    both in source dev mode and in the frozen Windows build, where git is not
    available.
    """
    global _cached_version, _cached_version, _cached_version, _cached_version
    if _cached_version is not None:
        version = None
        base = None
        if not os.environ.get('_MEIPASS2'):
            os.environ.get('_MEIPASS2')
        root = os.environ.get('_MEIPASS2')
        if root:
            base = root
        else:
            base = _BASE_DIR
        
        try:
            with open(os.path.join(base, 'app.version')) as f:
                version = f.read().strip()
        except Exception:
            version = None

        if version:
            _cached_version = version
            return _cached_version
        
        try:
            import subprocess
            result = subprocess.run([
                'git',
                'describe',
                '--tags',
                '--always',
                '--dirty'], cwd = _BASE_DIR, capture_output = True, text = True)
            if result.returncode == 0:
                _cached_version = result.stdout.strip()
                return _cached_version
            _cached_version = 'unknown'
        except Exception:
            _cached_version = 'unknown'
            return _cached_version

        return _cached_version
    return _cached_version


