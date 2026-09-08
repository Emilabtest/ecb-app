"""server_version.py — ships a per-deploy "build id" to every served page.

Long-open output/operator tabs keep running the OLD code after a redeploy and
silently stop following the server. A page-side poller compares the current
build id against the one embedded in its own HTML (`<meta name="x-build">`) and
reloads as soon as they differ, so stale tabs self-heal right after any deploy.

The build id is derived from the packaged executable (mtime + size) plus the
template tree, so it changes exactly when the deployed code changes.
"""

import os
import re
import sys
import json
import hashlib
from datetime import datetime

_DATA_DIR = 'data'
_DATAFILE = os.path.join(_DATA_DIR, 'server_version.json')
_META_RE = re.compile(r'<meta name="x-build"[^>]*>')
_HEAD_RE = re.compile(r'<head[^>]*>', re.IGNORECASE)


def _exe_identity():
    exe = getattr(sys, 'executable', None)
    try:
        if exe and os.path.exists(exe):
            st = os.stat(exe)
            return '%d-%d' % (st.st_size, int(st.st_mtime_ns))
    except OSError:
        pass
    return None


def _template_identity():
    here = os.path.dirname(os.path.abspath(__file__))
    mtimes = []
    base = os.path.join(here, 'templates')
    if os.path.isdir(base):
        for root, _dirs, files in os.walk(base):
            for fn in files:
                if fn.endswith('.html'):
                    try:
                        mtimes.append(int(os.stat(os.path.join(root, fn)).st_mtime_ns))
                    except OSError:
                        pass
    if mtimes:
        return '%d-%d' % (len(mtimes), max(mtimes))
    return None


def compute_build_id():
    """A short id that changes ONLY when a new build is deployed.

    In the packaged app the signature is taken from the executable file itself
    (size + mtime), which is stable across restarts and changes exactly when a
    new exe is copied over the running one. The template tree is only used as a
    fallback for dev runs (source layout), where the exe isn't present.
    """
    ident = _exe_identity()
    if ident:
        return hashlib.sha1(ident.encode('utf-8')).hexdigest()[:10]
    tpl = _template_identity()
    ident = '-'.join(x for x in (tpl, 'dev') if x)
    return hashlib.sha1(ident.encode('utf-8')).hexdigest()[:10]


def _read_meta():
    try:
        with open(_DATAFILE, 'r') as f:
            meta = json.load(f)
        if meta.get('build'):
            return meta
    except Exception:
        pass
    return None


def current_build():
    meta = _read_meta()
    if not meta:
        meta = {'build': compute_build_id()}
    return meta['build']


def ensure():
    """Persist the current build id to the data dir (bump detection baseline)."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    built = compute_build_id()
    meta = _read_meta()
    if not meta or meta.get('build') != built:
        meta = {'build': built, 'at': datetime.now().isoformat()}
        try:
            with open(_DATAFILE, 'w') as f:
                json.dump(meta, f)
        except OSError:
            pass
    return meta


def _inject(html, build):
    """Embed `<meta name="x-build">` right after <head> (idempotent)."""
    if _META_RE.search(html):
        return html
    m = _HEAD_RE.search(html)
    if not m:
        return html
    tag = '<meta name="x-build" content="%s">' % build
    return html[:m.end()] + tag + html[m.end():]


class BuildInject:
    """WSGI middleware: stamp every HTML response with the current build id.

    Per-request state lives in a closure (NOT instance attributes): under
    eventlet many greenlets call the same middleware instance concurrently, so
    shared mutable state would corrupt responses across requests. Non-HTML
    responses (e.g. the infinite MJPEG live feeds) are passed through UNCONSUMED
    and untouched — buffering them would hang the server forever.
    """

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def _noop_write(self, data):
        return len(data)

    def __call__(self, environ, start_response):
        state = {}

        def _start(status, headers, exc_info=None):
            state['status'] = status
            state['headers'] = headers
            state['exc_info'] = exc_info
            return self._noop_write

        body_iter = self.wsgi_app(environ, _start)
        status = state.get('status')
        headers = state.get('headers')
        if status is None or headers is None:
            # Inner app never started a response (shouldn't happen).
            start_response('500 INTERNAL SERVER ERROR', [('Content-Type', 'text/plain')])
            return [b'no response']

        content_type = next((v for k, v in headers if k.lower() == 'content-type'), '')
        if 'text/html' not in content_type.lower():
            # Infinite / binary streams (MJPEG, files) must pass through
            # untouched — never buffer them.
            start_response(status, headers, state.get('exc_info'))
            return body_iter

        chunks = []
        for chunk in body_iter:
            chunks.append(chunk)
        body = b''.join(chunks)
        if not body:
            start_response(status, headers, state.get('exc_info'))
            return [body]
        try:
            text = body.decode('utf-8', 'replace')
            injected = _inject(text, current_build())
            if injected != text:
                hdrs = [(k, v) for k, v in headers if k.lower() != 'content-length']
                start_response(status, hdrs, state.get('exc_info'))
                return [injected.encode('utf-8')]
        except Exception:
            pass
        start_response(status, headers, state.get('exc_info'))
        return [body]


def init_app(app, inject=True):
    ensure()
    from flask import jsonify

    @app.route('/api/server_version')
    def _server_version():
        return jsonify({'build': current_build()})

    if inject and not isinstance(app.wsgi_app, BuildInject):
        app.wsgi_app = BuildInject(app.wsgi_app)
    return app