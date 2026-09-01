# Source Generated with Decompyle++
# File: jsonio.pyc (Python 3.12)

import json
import os
import tempfile

def _unpatched_os():
    """Return the original (unpatched) `os` module for file choreography.

    Under eventlet's monkey-patch the green `os` wraps plain file descriptors in
    non-blocking pipes, which is unsupported on Windows (GreenPipe.fdopen ->
    set_nonblocking raises NotImplementedError). State writes would then throw.
    We use the pristine stdlib `os` so atomic_writes work identically on Linux
    and Windows. On non-eventlet deployments `os` is already the real module."""
    
    try:
        import eventlet.patcher as eventlet
        return eventlet.patcher.original('os')
    except Exception:
        return os



def atomic_write_json(path, data, *, indent = 2):
    '''Write JSON to `path` atomically: temp file in the same dir, fsync, then replace.

    Guarantees a concurrent reader sees either the old complete file or the new
    complete file ΓÇö never a partially-written one.
    '''
    d = os.path.dirname(os.path.abspath(path))
    osys = _unpatched_os()
    (fd, tmp) = tempfile.mkstemp(dir = d, prefix = '.tmp-', suffix = '.json')
    
    try:
        with osys.fdopen(fd, 'w') as f:
            json.dump(data, f, indent = indent)
            f.flush()
            osys.fsync(f.fileno())
        osys.replace(tmp, path)
        return None
    except BaseException:
        
        try:
            osys.unlink(tmp)
        except OSError:
            raise

        raise



