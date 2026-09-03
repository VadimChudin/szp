# -*- mode: python ; coding: utf-8 -*-
# Smart Zones Pro — PyInstaller Build Spec
# Собирает всё в один пакет БЕЗ окна консоли

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# Relocatable paths: resolve everything relative to this .spec file so the repo
# can live anywhere (no more hardcoded d:\smart-zones-pro).
REPO_DIR = os.path.dirname(os.path.abspath(SPECPATH))
PYTHON_CORE = os.path.join(REPO_DIR, 'python_core')

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
    'settings_window', 'paths', 'installer_gui',
    # ── Слой ИИ ──
    # ai.keygen сюда НЕ входит осознанно: генератор ключей содержит логику
    # выпуска лицензий и остаётся только у разработчика (см. excludes ниже).
    'proc_util', 'ai', 'ai.licensing', 'ai.ed25519', 'ai.hw_profile',
    'ai.model_catalog', 'ai.runtime', 'ai.downloader', 'ai.annotator',
    'ai.tools',
]

# ── Данные проекта (MQL файлы, splash) ──
datas += [
    (os.path.join(REPO_DIR, 'mql'), 'mql'),
    (os.path.join(REPO_DIR, 'splash_image.bmp'), '.'),
    # Грамматика ответа модели: без неё ИИ-слой не сможет ограничить вывод.
    (os.path.join(PYTHON_CORE, 'ai', 'zone_note.gbnf'), 'ai'),
]

# llama-server поставляется рядом с exe, если собран локально.
# Без него ИИ просто недоступен, остальной продукт работает как обычно.
if os.path.isdir(os.path.join(PYTHON_CORE, 'llama')):
    datas += [(os.path.join(PYTHON_CORE, 'llama'), 'llama')]

# Проверяем наличие splash.gif
if os.path.exists(os.path.join(PYTHON_CORE, 'splash.gif')):
    datas += [(os.path.join(PYTHON_CORE, 'splash.gif'), '.')]

a = Analysis(
    [os.path.join(PYTHON_CORE, 'app_entry.py')],
    pathex=[PYTHON_CORE],
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
        # Генератор лицензий не должен попадать клиенту ни в каком виде.
        'ai.keygen',
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
