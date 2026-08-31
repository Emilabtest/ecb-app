"""
windows_app_additions.py — RECOVERY NOTES for our Windows-specific additions
to the Leiturgia Flask app (app.py).

CONTEXT / OWNERSHIP
-------------------
The full `app.py` is the **darqlab/leiturgia** base (upstream, not ours) plus a
small set of **Windows-only additions** we made for the signed self-update
system. Because the base itself is upstream code (not ours) and is intentionally
not committed elsewhere in this backup repo, we preserve ONLY our additions here
so the Windows build can be reproduced on top of the upstream base.

These notes were recovered from the compiled `LeiturgiaServer.exe` via `pycdc`
(decompyle++) — the decompiler output is partially mangled on Python 3.12
bytecode, so treat this as authoritative *logic*, not verbatim source.

WHAT WE ADDED (on top of darqlab base)
---------------------------------------
1. `import updater` (top of app.py)
2. Helper functions:
     - `_update_config()`            — fresh-read config.json (update_url,
                                        enable_self_update are runtime settings)
     - `_update_install_dir()`       — returns os.getcwd() (the install folder)
     - `_write_update_status(payload)` — write data/update/status.json
3. Flask routes (registered as lambdas in app.py):
     - GET  /api/update/check  → updater.check_for_update(update_url, get_version())
     - POST /api/update/start  → download bundle to temp stage, then launch
                                 updater.exe apply <install_dir> <stage_dir> <manifest>
     - GET  /api/update/status → read data/update/status.json
     - (plus update-URL setting handling in settings route / settings.html)
4. `settings.html` is our Windows template (see templates/), with a
   `saveUpdateUrl()` + `checkForUpdate()` UI.

RECOVERED LOGIC (raw pycdc output, lightly reformatted)
--------------------------------------------------------
See the raw recovered lines below (verbatim from `app.pyc` decompilation) for
the /api/update/* handlers and the config helpers.
"""
# --------------------------------------------------------------------------- #
# RAW RECOVEREDPORTION (from app.pyc, decompile output)
# The following is preserved verbatim-ish so the exact logic is not lost.
# --------------------------------------------------------------------------- #
#
# def _update_config():
#     '''Read config.json fresh (update_url / enable_self_update are runtime
#     settings that may change between requests).'''
#     try:
#         with open('config.json') as _f:
#             return json.load(_f)
#     except Exception:
#         return {}
#
#
# def _update_install_dir():
#     '''The app runs with its working directory set to the install folder
#     (LeiturgiaServer.exe / Leiturgia.exe / config.json / license.dat /
#     updater.exe all live side-by-side).'''
#     return os.getcwd()
#
#
# def _write_update_status(payload):
#     try:
#         d = os.path.join('data', 'update')
#         os.makedirs(d, exist_ok=True)
#         with open(os.path.join(d, 'status.json'), 'w') as _f:
#             json.dump(payload, _f)
#     except Exception:
#         logger.warning('update status write failed', exc_info=True)
#
#
# # GET /api/update/check  ->  {"current", "latest", "available"}
# #     cfg = _update_config()
# #     update_url = cfg.get('update_url', '')
# #     if not update_url: return jsonify({status:error, message:'no update_url configured'}), 400
# #     info = updater.check_for_update(update_url, get_version())
# #     return jsonify({current, latest, available})
# #
# # POST /api/update/start -> {"status":"started", "target_version"}
# #     cfg = _update_config(); update_url = cfg.get('update_url', '')
# #     if not update_url: return 400
# #     info = updater.check_for_update(update_url, current_version)
# #     if not info.get('available'): return 409 already up to date
# #     # create data/update/lock (O_CREAT|O_EXCL), FileExistsError -> already running
# #     stage_dir = os.path.join(tempfile.gettempdir(), 'leiturgia_update_stage')
# #     shutil.rmtree(stage_dir, ignore_errors=True)
# #     updater.download_bundle(info['manifest'], stage_dir, update_url)
# #     manifest_path = os.path.join(stage_dir, 'manifest.json')
# #     write manifest
# #     applier = os.path.join(_update_install_dir(), 'updater.exe')
# #     subprocess.Popen([applier, 'apply', install_dir, stage_dir, manifest_path],
# #                      stdout=DEVNULL, stderr=DEVNULL,
# #                      creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
# #     _write_update_status({'status':'applying', ...})
# #     return jsonify({status:'started', target_version}), 202
# #     (on error: log + os.unlink(lock_path))
# #
# # GET /api/update/status -> contents of data/update/status.json
# #     try: with open(status_path) as _f: return jsonify(json.load(_f))
# #     except Exception: ...
# #
