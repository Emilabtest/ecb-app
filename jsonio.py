import json
import os
import uuid


def atomic_write_json(path, data, *, indent=2):
    """Write JSON to `path` atomically: temp file in the same dir, fsync, then replace.

    Guarantees a concurrent reader sees either the old complete file or the new
    complete file — never a partially-written one.
    """
    d = os.path.dirname(os.path.abspath(path))
    tmp = os.path.join(d, ".tmp-%s.json" % uuid.uuid4().hex)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
