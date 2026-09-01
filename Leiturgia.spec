# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the desktop launcher executable.
# Builds Leiturgia.exe (windowed) from desktop.py (pywebview wrapper that
# launches LeiturgiaServer.exe and opens the operator console).

a = Analysis(
    ['desktop.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'webview',
        'webview.platforms.winforms',
        'winforms',
        'clr',
    ],
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
    name='Leiturgia',
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
