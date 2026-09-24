# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for make_key.exe — owner-only license key generator.
# Console build; prompts for a HWID (or takes it as argv[1]) and prints the
# RSA license key. Needs the owner private key at runtime.

a = Analysis(
    ['make_key.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'licensing',
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
    name='make_key',
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
