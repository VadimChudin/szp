"""
sync_zones_to_mt4.py — Копирует zones_output.json в папку MT4 Files.

MQL4 может читать файлы только из:
  1. MQL4/Files/              (локальная папка терминала)
  2. Terminal/Common/Files/   (общая папка, FILE_COMMON)

Этот скрипт находит папку MT4 и копирует JSON туда.
Запускается автоматически после каждого пересчёта зон.
"""

import shutil
import os
import sys
from pathlib import Path

import paths

# Источник — JSON от Python Core (разрешается через paths.py).
SOURCE = paths.ZONES_FILE


def find_mt4_common_files() -> Path | None:
    """Ищет папку Common/Files от MetaTrader 4/5."""
    common = paths.MT_COMMON_FILES
    if common and common.exists():
        print(f"[sync] Found MT Common Files: {common}")
        return common

    terminal_base = paths.MT_TERMINAL_ROOT
    if terminal_base and terminal_base.exists():
        for sub in terminal_base.iterdir():
            if sub.is_dir():
                files_dir = sub / "MQL4" / "Files"
                if files_dir.exists():
                    print(f"[sync] Found MT4 Files dir: {files_dir}")
                    return files_dir
    return None


def find_mt4_indicators_dir() -> Path | None:
    """Ищет папку MQL4/Indicators для установки индикатора."""
    terminal_base = paths.MT_TERMINAL_ROOT
    if terminal_base and terminal_base.exists():
        for sub in terminal_base.iterdir():
            if sub.is_dir():
                ind_dir = sub / "MQL4" / "Indicators"
                if ind_dir.exists():
                    return ind_dir
    return None


def sync_zones():
    """Копирует zones_output.json в папку MT4 Common/Files."""
    if not SOURCE.exists():
        print(f"[sync] Source file not found: {SOURCE}")
        print(f"[sync] Run bridge_server.py first!")
        return False

    target_dir = find_mt4_common_files()
    if target_dir:
        dest = target_dir / "zones_output.json"
        shutil.copy2(SOURCE, dest)
        print(f"[sync] Copied zones to: {dest}")
        return True
    else:
        print("[sync] MT4 Common/Files not found.")
        return False


def find_all_terminals() -> list[tuple[str, Path]]:
    """Находит ВСЕ установленные терминалы MT4 и MT5 (по хэш-папкам)."""
    terminal_base = paths.MT_TERMINAL_ROOT
    terminals: list[tuple[str, Path]] = []
    if terminal_base and terminal_base.exists():
        for sub in terminal_base.iterdir():
            if sub.is_dir():
                if (sub / "MQL4").exists():
                    terminals.append(("MT4", sub))
                if (sub / "MQL5").exists():
                    terminals.append(("MT5", sub))
    return terminals


def find_metaeditor(terminal_path: Path, is_mt5: bool) -> Path | None:
    """
    Ищет metaeditor.exe для компиляции .mq4 / .mq5 файлов.
    Быстрый поиск: сначала через origin.txt терминала, потом по стандартным путям.
    """
    import glob
    
    # Метод 1: Читаем origin.txt из папки терминала (содержит путь установки MT4/MT5)
    origin = terminal_path / "origin.txt"
    if origin.exists():
        try:
            install_path = Path(origin.read_text(encoding='utf-16').strip())
            # Для MT5 предпочтительнее metaeditor64.exe
            if is_mt5:
                me64 = install_path / "metaeditor64.exe"
                if me64.exists(): return me64
                me = install_path / "metaeditor.exe"
                if me.exists(): return me
            else:
                me = install_path / "metaeditor.exe"
                if me.exists(): return me
                me64 = install_path / "metaeditor64.exe"
                if me64.exists(): return me64
        except Exception:
            pass
    
    # Метод 2: Стандартные места установки
    search_paths = [
        r"C:\Program Files\MetaTrader 5",
        r"C:\Program Files*\*MetaTrader*",
        r"C:\Program Files*\*MT4*",
        r"D:\*MetaTrader*",
        r"D:\*MT4*",
        r"C:\MT4*",
        r"C:\MT5*",
    ]
    
    for pattern in search_paths:
        for folder in glob.glob(pattern):
            if is_mt5:
                me64 = Path(folder) / "metaeditor64.exe"
                if me64.exists(): return me64
                me = Path(folder) / "metaeditor.exe"
                if me.exists(): return me
            else:
                me = Path(folder) / "metaeditor.exe"
                if me.exists(): return me
                me64 = Path(folder) / "metaeditor64.exe"
                if me64.exists(): return me64
    return None


def compile_mq(mq_path: Path, terminal_path: Path, is_mt5: bool) -> bool:
    """Компилирует .mq4 или .mq5 файл через metaeditor.exe."""
    import subprocess
    
    me = find_metaeditor(terminal_path, is_mt5)
    if me is None:
        print(f"[install] metaeditor not found for {mq_path.name}. Please compile manually:")
        print(f"  Press F4 in Terminal, open {mq_path}, press F7")
        return False
    
    print(f"[install] Compiling with: {me}")
    try:
        # Для MT5/MT4 ключи компиляции одинаковые
        result = subprocess.run(
            [str(me), "/compile:" + str(mq_path), "/log"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print(f"[install] [OK] Compiled: {mq_path.name}")
            return True
        else:
            print(f"[install] Compilation returned code {result.returncode}")
            return False
    except Exception as e:
        print(f"[install] Compilation error: {e}")
        return False


def install_all():
    """
    Автоматическая установка ВСЕХ компонентов Smart Zones Pro в MT4 и MT5:
      1. Индикатор StrongZones.mq4 / .mq5
      2. EA SmartZonesCollector.mq4 (только для MT4)
      3. Компиляция файлов через metaeditor.exe
    """
    base = paths.BASE_DIR

    terminals = find_all_terminals()
    
    if not terminals:
        print("[install] ✗ No MT4/MT5 terminals found!")
        return False
    
    print(f"[install] Found {len(terminals)} MetaTrader terminal(s)")
    
    installed = 0
    for term_type, term_path in terminals:
        term_name = term_path.name[:8] + "..."
        print(f"\n[install] Terminal ({term_type}): {term_name}")
        
        if term_type == "MT4":
            indicator_src = base / "mql" / "MT4" / "Indicators" / "StrongZones.mq4"
            ea_src = base / "mql" / "MT4" / "Experts" / "SmartZonesCollector.mq4"
            
            # --- MT4 Индикатор ---
            ind_dir = term_path / "MQL4" / "Indicators"
            if ind_dir.exists() and indicator_src.exists():
                dest = ind_dir / "StrongZones.mq4"
                shutil.copy2(indicator_src, dest)
                print(f"  [OK] Indicator -> {dest.name}")
                compile_mq(dest, term_path, False)
                
            # --- MT4 EA ---
            ea_dir = term_path / "MQL4" / "Experts"
            if ea_dir.exists() and ea_src.exists():
                dest = ea_dir / "SmartZonesCollector.mq4"
                shutil.copy2(ea_src, dest)
                print(f"  [OK] EA -> {dest.name}")
                compile_mq(dest, term_path, False)
                
            installed += 1
            
        elif term_type == "MT5":
            indicator_src = base / "mql" / "MT5" / "Indicators" / "StrongZones.mq5"
            ea_src = base / "mql" / "MT5" / "Experts" / "SmartZonesCollector.mq5"

            # --- MT5 Индикатор ---
            ind_dir = term_path / "MQL5" / "Indicators"
            if ind_dir.exists() and indicator_src.exists():
                dest = ind_dir / "StrongZones.mq5"
                shutil.copy2(indicator_src, dest)
                print(f"  [OK] Indicator -> {dest.name}")
                compile_mq(dest, term_path, True)

            # --- MT5 EA (брокерские данные → CSV) ---
            ea_dir = term_path / "MQL5" / "Experts"
            if ea_dir.exists() and ea_src.exists():
                dest = ea_dir / "SmartZonesCollector.mq5"
                shutil.copy2(ea_src, dest)
                print(f"  [OK] EA -> {dest.name}")
                compile_mq(dest, term_path, True)

            installed += 1
    
    # ── Синхронизация zones_output.json ───────────────────────────
    sync_zones()
    
    print(f"\n{'='*50}")
    print(f"  Installation complete! Patched {installed} terminal(s).")
    print(f"{'='*50}\n")
    return installed > 0


if __name__ == "__main__":
    import sys
    install_all()

