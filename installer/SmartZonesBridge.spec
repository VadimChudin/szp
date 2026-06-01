# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

# Relocatable: resolve paths relative to this .spec (no hardcoded d:\smart-zones-pro).
REPO_DIR = os.path.dirname(os.path.abspath(SPECPATH))
PYTHON_CORE = os.path.join(REPO_DIR, 'python_core')

datas = []
binaries = []
hiddenimports = ['pandas', 'numpy', 'yfinance', 'requests', 'mplfinance', 'matplotlib',
                 'settings_window', 'pystray', 'PIL', 'paths']
tmp_ret = collect_all('yfinance')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('mplfinance')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    [os.path.join(PYTHON_CORE, 'app_entry.py')],
    pathex=[PYTHON_CORE],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'tensorflow', 'scipy', 'sympy', 'numba', 'llvmlite', 'psycopg2', 'sqlalchemy', 'botocore', 'boto3', 'cryptography', 'bcrypt', 'PIL', 'lxml'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SmartZonesBridge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SmartZonesBridge',
)
