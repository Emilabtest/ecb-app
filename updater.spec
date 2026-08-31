# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for updater.exe (the standalone signed-update applier).
# Console build -- it logs to stdout while applying an update.

a = Analysis(
    ['updater_apply.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'licensing',
        'updater',
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
    name='updater',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
