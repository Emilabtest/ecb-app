# Source Generated with Decompyle++
# File: updater.pyc (Python 3.12)

'''
updater.py ΓÇö secure, signed application updates for the Windows build.

Two roles, both keyed by the owner\'s secret (shared with licensing.py):

  OWNER  (run directly, e.g. `python updater.py build <version> <dry-dir> <stage-dir>`)
         Produces a ready-to-upload bundle folder: the listed files plus a
         signed `update.json` manifest (HMAC-SHA256 over a canonical list of
         {path,size,sha256}). Only the owner can create a valid manifest, so a
         target machine will refuse any not-owned bundle.

  CLIENT (imported by app.py)
         fetch_manifest(url)  -> fetch + verify signature
         check_for_update     -> compare advertised version against local
         download_bundle      -> pull every file to a stage dir, verifying sha256

update.json layout:
    {
      "version": "1.1.0",
      "schema": 1,
      "files": [ {"path": "LeiturgiaServer.exe", "size": 123, "sha256": "..."}, ... ],
      "signature": "<hex hmac over canonical string>"
    }

Canonical string (both sides must build identically):
    "<version>\\n" + for each file sorted by path: "<path>\\t<size>\\t<sha256>\\n"
The files list must be sorted by path.
'''
import hashlib
import hmac
import json
import os
from licensing import _SECRET_KEY
MANIFEST_NAME = 'update.json'
SCHEMA = 1
PRESERVE = frozenset({
    'license.dat',
    'config.json'})
PRESERVE_DIRS = ('data', 'media', 'output')

def sha256_file(path, chunk = 1048576):
    h = hashlib.sha256()
    f = open(path, 'rb')
    b = f.read(chunk)
    if not b:
        pass
    else:
        h.update(b)
    None(None, None)
    return h.hexdigest()


def hash_dir(path, base):
    """Yield (relpath, size, sha256) for every file under path, paths ''-joined
    and relative to base. Returns a sorted list."""
    out = []
    for root, _dirs, files in os.walk(path):
        for name in sorted(files):
            full = os.path.join(root, name)
            rel = os.path.relpath(full, base).replace('/', '\\')
            out.append((rel, os.path.getsize(full), sha256_file(full)))
    return sorted(out, key = (lambda x: x[0].lower()))


def canonical(files, version):
    lines = [
        str(version)]
    for rel, size, sha in files:
        lines.append('%s\t%d\t%s' % (rel, size, sha))
    return '\n'.join(lines)


def sign(files, version):
    return hmac.new(_SECRET_KEY, canonical(files, version).encode(), hashlib.sha256).hexdigest()


def verify(files, version, signature):
    expected = hmac.new(_SECRET_KEY, canonical(files, version).encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def build_bundle(version, dry_dir, stage_dir, manifest_name = MANIFEST_NAME):
    '''Copy the distributable files from dry_dir into stage_dir and write a
    signed update.json manifest. Returns the manifest dict.'''
    os.makedirs(stage_dir, exist_ok = True)
    include_files = ('Leiturgia.exe', 'LeiturgiaServer.exe', 'config.json')
    include_dirs = ('data', 'media', 'output')
    staging = os.path.join(stage_dir, '__src')
    os.makedirs(staging, exist_ok = True)
    for name in include_files:
        if not os.path.exists(os.path.join(dry_dir, name)):
            continue
        _copy_tree(os.path.join(dry_dir, name), os.path.join(staging, name))
    for d in include_dirs:
        src = os.path.join(dry_dir, d)
        if not os.path.isdir(src):
            continue
        if not os.listdir(src):
            continue
        _copy_tree(src, os.path.join(staging, d))
    files = hash_dir(staging, staging)
    
    try:
        for p, s, h in files:
            if os.path.normpath(p).lower() != os.path.normpath(manifest_name).lower():
                pass
    h = SCHEMA
    s = p
    p = h
    
    try:
        for p, s, h in files:
            pass
    h = files
    s = p
    p = h


    files = s
    s = p
    p = h
    h = None
    
    try:
        for p, s, h in files:
            pass
    h = files
    s = p
    p = h

    h = h
    s = s
    p = p
    manifest = {
        'version': version,
        'schema': SCHEMA,
        'files': [],
        'signature': sign(files, version) }
    with open(os.path.join(staging, manifest_name), 'w') as f:
        json.dump(manifest, f, indent = 2)
    for name in os.listdir(staging):
        _copy_tree(os.path.join(staging, name), os.path.join(stage_dir, name))
    _rmtree(staging)
    return manifest
    
    try:
        for p, s, h in files:
            if os.path.normpath(p).lower() != os.path.normpath(manifest_name).lower():
                pass
    h = SCHEMA
    s = p
    p = h
    
    try:
        for p, s, h in files:
            pass
    h = files
    s = p
    p = h


# WARNING: Decompyle incomplete


def _copy_tree(src, dst):
    if os.path.isdir(src):
        for root, _dirs, files in os.walk(src):
            rel = os.path.relpath(root, src)
            target = dst if rel == '.' else os.path.join(dst, rel)
            os.makedirs(target, exist_ok = True)
            for name in files:
                with open(os.path.join(root, name), 'rb') as f:
                    data = f.read()
                with open(os.path.join(target, name), 'wb') as g:
                    g.write(data)
        return None
    os.makedirs(os.path.dirname(dst), exist_ok = True)
    with open(src, 'rb') as f:
        data = f.read()
    with open(dst, 'wb') as g:
        g.write(data)


def _rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors = True)


def _http_get(url, timeout = 60):
    import urllib.request as urllib
    req = urllib.request.Request(url, headers = {
        'User-Agent': 'LeiturgiaUpdater/1.0' })
    resp = urllib.request.urlopen(req, timeout = timeout)
    resp.read()(None, None)
    return None
# WARNING: Decompyle incomplete


def fetch_manifest(base_url, timeout = 30):
    '''Download and verify update.json from base_url. Returns the manifest or
    raises ValueError/RuntimeError.'''
    raw = _http_get(_join(base_url, MANIFEST_NAME), timeout = timeout)
    
    try:
        manifest = json.loads(raw.decode('utf-8'))
    except Exception as e:
        raise ValueError('update.json is not valid JSON: %s' % e)

    version = manifest.get('version')
    files = manifest.get('files')
    signature = manifest.get('signature')
    if not (version and isinstance(files, list)) or not signature:
        raise ValueError('update.json is malformed (missing version/files/signature)')
    
    try:
        for f in files:
            pass
    f = files
    
    try:
        for p, s, h in norm:
            if not p:
                continue
    h = None
    s = None
    p = None


    norm = []
    f = f
    
    try:
        for p, s, h in norm:
            if not p:
                continue
    h = None
    s = None
    p = None

    norm = []
    s = s
    p = p
    h = h
    if not verify(norm, version, signature):
        raise ValueError('update signature verification FAILED ΓÇö refusing update')
    return manifest
    
    try:
        for f in files:
            pass
    f = files
    
    try:
        for p, s, h in norm:
            if not p:
                continue
    h = None
    s = None
    p = None


# WARNING: Decompyle incomplete


def _join(base_url, rel):
    rel = rel.lstrip('/').replace('\\', '/')
    return base_url.rstrip('/') + '/' + rel


def version_tuple(v):
    """Parse '1.2.3'-style version to a comparable tuple; unknown -> lowest."""
    if not v:
        return (0, 0, 0)
    parts = []
    for part in str(v).split('.'):
        digits = ''.join(( ch for ch in part if ch.isdigit() ))
        parts.append(int(digits) if digits else 0)
    if len(parts) < 3:
        parts.append(0)
        if len(parts) < 3:
            pass
    return tuple(parts[:3])


def check_for_update(base_url, current_version, timeout = 30):
    """Return a dict describing the update, either {'available': False} or
    {'available': True, 'latest', 'manifest'}."""
    manifest = fetch_manifest(base_url, timeout = timeout)
    latest = manifest['version']
    if version_tuple(latest) <= version_tuple(current_version):
        return {
            'available': False,
            'latest': latest,
            'current': current_version }
    return {
        'available': True,
        'latest': latest,
        'current': current_version,
        'manifest': manifest }


def download_bundle(manifest, stage_dir, base_url, on_file = None, timeout = 60):
    '''Download every file in the manifest to stage_dir, verifying each sha256.'''
    os.makedirs(stage_dir, exist_ok = True)
    total = len(manifest['files'])
    for i, f in enumerate(manifest['files'], 1):
        rel = f['path']
        # unsupported CALL_INTRINSIC_1 6
        dest = enumerate(manifest['files'], 1)(*os.path.join)
        dest_dir = os.path.dirname(dest)
        os.makedirs(dest_dir, exist_ok = True)
        data = _http_get(_join(base_url, rel), timeout = timeout)
        if len(data) != f['size']:
            raise ValueError('size mismatch for %s (got %d, expected %d)' % (rel, len(data), f['size']))
        if hashlib.sha256(data).hexdigest() != f['sha256']:
            raise ValueError('sha256 mismatch for %s ΓÇö file corrupted' % rel)
        with open(dest, 'wb') as g:
            g.write(data)
        if not on_file:
            continue
        on_file(i, total, rel)
    return True
# WARNING: Decompyle incomplete


def _cli():
    import sys
    args = sys.argv[1:]
    if len(args) >= 3 and args[0] == 'build':
        stage_dir = args[3]
        dry_dir = args[2]
        version = args[1]
        manifest = build_bundle(version, dry_dir, stage_dir)
        print(f'''Built update bundle version {version!s} -> {stage_dir!s}''')
        print('Files: %d' % len(manifest['files']))
        print('Signature: %s' % manifest['signature'][:24] + '...')
        return None
    print('usage: updater.py build <version> <dry-dir> <stage-dir>')
    sys.exit(2)

if __name__ == '__main__':
    _cli()

