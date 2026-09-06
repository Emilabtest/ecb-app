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


def _ensure_config():
    """Create a default config.json on first run so a fresh install can boot
    (and can be activated) without shipping an owner's secrets.  The default
    operator PIN is 1234 (sha256); the operator can change it from Settings."""
    import json as _json
    if os.path.isfile('config.json'):
        return
    import hashlib as _hl
    import secrets as _sec
    _cfg = {
        'pin_hash': _hl.sha256(b'1234').hexdigest(),
        'session_secret': _sec.token_urlsafe(32),
        'session_timeout_hours': 8,
        'max_login_attempts': 5,
        'cloud_enabled': False,
        'cloud_url': '',
        'cloud_token': '',
        'enable_self_update': True,
        'update_url': 'https://github.com/Emilabtest/ecb-app/releases/latest/download',
        'owner_email': '',
        'log_level': 'INFO',
        'media_video_budget_gb': 2,
        'media_image_budget_gb': 1,
        'media_disk_reserve_gb': 1,
        'media_warn_percent': 80,
        'media_video_dir': os.path.join(HERE, 'media', 'videos'),
        'projection_aspects': {'ch1': 'off'},
    }
    try:
        with open('config.json', 'w') as _f:
            _json.dump(_cfg, _f, indent=2)
    except OSError:
        pass


_ensure_config()

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


_ACT_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Leiturgia &mdash; Device Activation</title>
<style>
  :root{--gold:#d4af37;--bg:#0f1117;--card:#181b24;--line:#2a2f3d;--txt:#e8e6e3;--muted:#9aa0ae}
  *{box-sizing:border-box} body{margin:0;font-family:Segoe UI,system-ui,sans-serif;background:var(--bg);color:var(--txt);display:flex;min-height:100vh;align-items:center;justify-content:center;padding:24px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:34px 38px;max-width:580px;width:100%;box-shadow:0 10px 40px rgba(0,0,0,.45)}
  h1{font-size:1.35rem;margin:0 0 6px} p{color:var(--muted);font-size:.92rem;line-height:1.55;margin:6px 0;font-weight:400}
  .hwid{background:#0b0e14;border:1px dashed var(--line);border-radius:8px;padding:12px 14px;font-family:Consolas,monospace;font-size:.8rem;word-break:break-all;color:var(--gold);user-select:all;margin-top:4px}
  label{display:block;font-size:.8rem;color:var(--muted);margin:18px 0 6px}
  input{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:#0b0e14;color:var(--txt);font-family:Consolas,monospace;font-size:.85rem}
  button{margin-top:14px;width:100%;padding:12px;border:0;border-radius:8px;background:var(--gold);color:#151207;font-weight:700;font-size:.95rem;cursor:pointer}
  button:disabled{opacity:.5;cursor:wait}
  .msg{border-radius:8px;padding:10px 12px;margin-top:16px;font-size:.85rem;display:none}
  .msg.err{background:#3a1b1f;color:#ffb4a8;display:block} .msg.ok{background:#14321f;color:#a8f0c3;display:block}
  .row{display:flex;gap:10px;margin-top:14px;width:100%}
  .row button{flex:1;margin-top:0;background:#1e2430;color:#e8e6e3;border:1px solid var(--line)}
  code{color:var(--gold)}
</style></head><body><div class="card">
  <h1>Leiturgia is not activated</h1>
  <p>This copy needs a license key for <b>this PC</b>. Send your Hardware ID below to your Leiturgia provider,
     paste the license key you receive, then press <b>Activate device</b>.</p>
  <label>Hardware ID &mdash; send this to your provider</label>
  <div class="hwid">{{ hwid }}</div>
  <label>License key</label>
  <input id="key" autocomplete="off" spellcheck="false" placeholder="Paste license key here">
  <button id="act" onclick="activate()">Activate device</button>
  <div class="row">
    <button id="email" onclick="sendHWID()">Send HWID by email</button>
    <button id="copy" onclick="copyHWID()">Copy HWID</button>
  </div>
  <div class="msg" id="msg"></div>
  <div id="done" style="display:none">
    <div class="msg ok">Activated &mdash; loading Leiturgia&hellip;</div>
    <p>Your default sign-in PIN is <code>1234</code> &mdash; change it afterwards.</p>
  </div>
</div>
<script>
  var _hwid = (document.querySelector('.hwid')||{}).textContent ? document.querySelector('.hwid').textContent.trim() : '{{ hwid }}';
  async function copyHWID(){
    try{ await navigator.clipboard.writeText(_hwid); }
    catch(e){
      var ta=document.createElement('textarea'); ta.value=_hwid; document.body.appendChild(ta); ta.select();
      try{ document.execCommand('copy'); }catch(_){}
      document.body.removeChild(ta);
    }
    var m=document.getElementById('msg'); m.className='msg ok'; m.textContent='Hardware ID copied.';
  }
  function sendHWID(){
    var owner='{{ owner_email }}';
    if(!owner){ copyHWID(); return; }
    var sub=encodeURIComponent('Leiturgia License Request');
    var body=encodeURIComponent('Please create a license key for this PC.\n\nHardware ID: ' + _hwid);
    location.href='mailto:'+owner+'?subject='+sub+'&body='+body;
  }
async function activate(){
  const key = document.getElementById('key').value.trim();
  const msg = document.getElementById('msg');
  const btn = document.getElementById('act');
  msg.className='msg'; msg.textContent='';
  if(!key){ msg.className='msg err'; msg.textContent='Paste the license key first.'; return; }
  btn.disabled=true; btn.textContent='Activating…';
  try{
    const r = await fetch('/api/lic/activate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key})});
    const d = await r.json();
    if(d.ok){
      document.getElementById('done').style.display='block';
      msg.className='msg ok'; msg.textContent='Activated. Reloading…';
      setTimeout(function(){ location.href='/login'; }, 2000);
    } else {
      msg.className='msg err'; msg.textContent='Activation failed: '+(d.message||'unknown error');
    }
  }catch(e){ msg.className='msg err'; msg.textContent='Network error — is the app still running?'; }
  btn.disabled=false; btn.textContent='Activate device';
}
</script></body></html>'''


def _write_licence_error(reason):
    os.makedirs('data', exist_ok=True)
    with open(os.path.join('data', 'license_error.log'), 'w') as f:
        f.write('Leiturgia is locked to a specific machine.\n')
        f.write('Reason: %s\n' % reason)
        f.write('This copy is not licensed for this PC. Contact the owner.\n')


from licensing import verify_licence

# Per-machine licence state.  When not licensed the running server only serves
# the activation page (+ /api/lic/* + a locked /api/health); when a valid key is
# submitted the state flips in-process, so no restart / port hand-off is needed.
_lic_state = {'ok': False, 'hwid': ''}

_lic_ok, _lic_reason = verify_licence()
if not _lic_ok:
    _write_licence_error(_lic_reason)
_lic_state['ok'] = _lic_ok


def wire_license_gate():
    """Add the licence gate to the running Flask app (called after the full
    app object exists).  While not licensed, every request other than the
    activation endpoints / a locked /api/health is short-circuited to the
    activation page.  A valid key writes license.dat and flips the state to
    unlocked in-process."""
    import hashlib as _hl
    import hmac as _hm
    from licensing import get_hardware_id, make_licence
    from flask import request, jsonify, Response

    _lic_state['hwid'] = get_hardware_id()
    try:
        import json as _json
        with open('config.json') as _f:
            _lic_state['owner_email'] = (_json.load(_f) or {}).get('owner_email') or ''
    except Exception:
        _lic_state['owner_email'] = ''

    try:
        from version import get_version as _gv
        _ver = _gv()
    except Exception:
        _ver = 'unknown'

    def _page_html(forced_hwid):
        _owner = (_lic_state.get('owner_email') or '').strip()
        _h = forced_hwid or 'UNAVAILABLE'
        return (_ACT_HTML.replace('{{ hwid }}', _h)
                          .replace('{{ owner_email }}', _owner))

    @app.before_request
    def _gate():
        if _lic_state['ok']:
            return None
        p = request.path
        if p in ('/api/lic/status', '/api/lic/activate'):
            return None
        if p == '/api/health':
            return jsonify(status='locked', licensed=False, version=_ver)
        if p.startswith('/static') or p in ('/favicon.ico',):
            return None
        return Response(_page_html(_lic_state['hwid']), status=200, mimetype='text/html')

    @app.route('/api/lic/status')
    def _lic_status():
        if _lic_state['ok']:
            return jsonify(licensed=True, hwid=_lic_state['hwid'])
        return jsonify(licensed=False, hwid=_lic_state['hwid'],
                       reason='Missing or invalid license.dat for this PC')

    @app.route('/api/lic/activate', methods=['POST'])
    def _lic_activate():
        if _lic_state['ok']:
            return jsonify(ok=False, message='Already activated.')
        data = request.get_json(force=True, silent=True) or {}
        key = (data.get('key') or '').strip()
        if not _lic_state['hwid']:
            return jsonify(ok=False, message='Could not read this PC hardware ID.')
        if not key:
            return jsonify(ok=False, message='Enter a license key.')
        expected = make_licence(_lic_state['hwid'])
        if not _hm.compare_digest(key, expected):
            return jsonify(ok=False, message='License key is not valid for this PC.')
        try:
            with open('license.dat', 'w') as f:
                f.write(key)
        except OSError as e:
            return jsonify(ok=False, message='Could not write license.dat: %s' % e)
        _lic_state['ok'] = True
        return jsonify(ok=True, message='Activated.')


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

# Add the licence gate once the full Flask app object exists.
wire_license_gate()

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
