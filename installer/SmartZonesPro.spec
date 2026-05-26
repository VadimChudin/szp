# -*- mode: python ; coding: utf-8 -*-
# Smart Zones Pro — PyInstaller Build Spec
# Собирает всё в один пакет БЕЗ окна консоли

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# ── Собираем зависимости ──
datas = []
binaries = []
hiddenimports = [
    'pandas', 'numpy', 'requests',
    'MetaTrader5', 'webview', 'pystray',
    'PIL', 'PIL.Image', 'PIL.ImageDraw',
    'tkinter', 'json', 'threading', 'multiprocessing',
    'clr',  # для webview на Windows
]

# webview нуждается в pythonnet/clr
for pkg in ['webview', 'clr_loader', 'pythonnet']:
    try:
        tmp = collect_all(pkg)
        datas += tmp[0]; binaries += tmp[1]; hiddenimports += tmp[2]
    except Exception:
        pass

# MetaTrader5 имеет нативные DLL
try:
    tmp = collect_all('MetaTrader5')
    datas += tmp[0]; binaries += tmp[1]; hiddenimports += tmp[2]
except Exception:
    pass

# pystray
try:
    tmp = collect_all('pystray')
    datas += tmp[0]; binaries += tmp[1]; hiddenimports += tmp[2]
except Exception:
    pass

# ── Все наши модули ──
hiddenimports += [
    'config', 'data_fetcher', 'volume_filter', 'zone_detector',
    'fvg_detector', 'bridge_server', 'footprint_data', 'footprint_window',
    'tick_reader', 'sync_zones_to_mt4', 'persistent_zones',
    'telegram_bot', 'smart_zones_tray', 'dukascopy_loader',
]

# ── Данные проекта (MQL файлы, splash) ──
datas += [
    ('d:\\smart-zones-pro\\mql', 'mql'),
    ('d:\\smart-zones-pro\\splash_image.bmp', '.'),
]

# Проверяем наличие splash.gif
import os
if os.path.exists('d:\\smart-zones-pro\\python_core\\splash.gif'):
    datas += [('d:\\smart-zones-pro\\python_core\\splash.gif', '.')]

a = Analysis(
    ['d:\\smart-zones-pro\\python_core\\app_entry.py'],
    pathex=['d:\\smart-zones-pro\\python_core'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch', 'tensorflow', 'scipy', 'sympy', 'numba', 'llvmlite',
        'psycopg2', 'sqlalchemy', 'botocore', 'boto3', 'cryptography',
        'bcrypt', 'lxml', 'matplotlib', 'mplfinance', 'yfinance',
        'IPython', 'notebook', 'jupyter',
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SmartZonesPro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # ← КЛЮЧЕВОЕ: никаких окон терминала!
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='app_icon.ico',  # Раскомментировать когда будет иконка
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SmartZonesPro',
)
