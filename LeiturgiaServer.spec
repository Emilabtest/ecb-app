# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the embedded Leiturgia server executable.
# Builds LeiturgiaServer.exe (windowed) from server_entry.py.
#
# The recovered .pyc project modules (app, roles, updater, licensing, etc.)
# live in pymod/ and are loaded sourceless at runtime by server_entry.py.
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ['server_entry.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('pymod', 'pymod'),
        ('templates', 'templates'),
        ('static', 'static'),
        ('data', 'data'),
        ('app.version', '.'),
    ],
    hiddenimports=[
        'eventlet.hubs.epolls',
        'eventlet.hubs.kqueue',
        'eventlet.hubs.poll',
        'eventlet.hubs.selects',
        'eventlet.green.thread',
        'eventlet.green.threading',
        'eventlet.websocket',
        'engineio.async_drivers.threading',
        'engineio.async_drivers.eventlet',
        'socketio',
        'flask_limiter',
        'flask_limiter.util',
        'python_dotenv',
        'dotenv',
        'live_input',
        'cv2',
        'numpy',
        'sqlite3',
        'asyncio',
        'ctypes',
        'websockets',
        'wsproto',
        'bidict',
        'requests',
        'urllib3',
        'certifi',
        'idna',
        'charset_normalizer',
        'mutagen',
    ] + collect_submodules('dns') + collect_submodules('websockets') + collect_submodules('requests') + collect_submodules('wsproto'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='LeiturgiaServer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
