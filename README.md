# Leiturgia — Windows build (source recovery backup)

This repository is a **backup of the Microsoft Windows build source** of the
Leiturgia app, recovered from our own compiled executables
(`LeiturgiaServer.exe`, `updater.exe`, `Leiturgia.exe`) after the original
source tree was lost during a failed update apply.

> **Attribution / ownership**
> The Leiturgia application itself is built on top of the **darqlab/leiturgia**
> open-source project (Python/Flask + Socket.IO). We do **not** claim ownership
> of that base code, and the darqlab base modules (e.g. `app.py`, `cloud_agent.py`,
> `hymnal.py`, and the core data model) are **not** included here. See
> <https://github.com/darqlab/leiturgia> for the upstream base.
>
> What is included here is **our own Windows-specific build work**: the signed
> updater system, the machine-lock licensing helper, the Windows server entry
> point, our packaged templates/static assets, and the PyInstaller build specs.

## What's in here (our code)

| File | Purpose |
|------|---------|
| `updater.py` | Owner side: `python updater.py build <version> <dry-dir> <stage-dir>` produces a signed update bundle (HMAC-SHA256 `update.json`). Client side: `check_for_update()` / `download_bundle()` used by the server. |
| `updater_apply.py` | The standalone applier compiled to `updater.exe`. Run as `updater.exe apply <install_dir> <stage_dir> <manifest_json>`: stops processes, backs up user files, clears + installs the new signed bundle, restores user files, writes status, relaunches. |
| `licensing.py` | Machine-lock licensing. `hwid` prints this machine's Hardware ID (SHA-256 of the Windows `MachineGuid`); `gen <hwid>` signs it (owner-only, uses `_SECRET_KEY`). The server refuses to start without a valid `license.dat`. |
| `server_entry.py` | PyInstaller entry point for `LeiturgiaServer.exe`. Freeze-safe working dir, licence check, dir creation, temp cleanup, then `socketio.run(...)` on `0.0.0.0:5001`. |
| `templates/`, `static/`, `app.version` | Our packaged assets. `templates/settings.html` is our Windows UI (includes `/api/update/*` and update-URL endpoints). `app.version` = `1.1.0`. |
| `LeiturgiaServer.spec`, `updater.spec` | PyInstaller build specs. |
| `app.py` — Windows additions | See `windows_app_additions.py` for the **changes we made on top of the darqlab base** (the `/api/update/*` endpoints, `config.json` update settings, and helper functions). The full `app.py` is upstream base code and is intentionally not committed here. |

## Building (optional)

With the upstream darqlab base checked out at the repo root, add our Windows
files, then:

```bat
:: rebuild the server executable
pyinstaller --noconfirm LeiturgiaServer.spec

:: rebuild the updater
pyinstaller --noconfirm updater.spec
```

Requires: Python 3.12, PyInstaller, Flask, Flask-SocketIO, eventlet, and the
dependencies of the upstream app.

## Notes

- `_SECRET_KEY` in `licensing.py` is preserved from the original build so any
  newly built executables remain signature-compatible with existing
  deployments and licences.
- This is a disaster-recovery backup; the checked-in `.py` files were
  reconstructed from our own compiled bytecode (via `pycdc` disassembly +
  recovery) and from our previously-read source, and are intended to match the
  original build.
