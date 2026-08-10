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
from datetime import datetime
from pathlib import Path

import paths
import version

# Источник — JSON от Python Core (разрешается через paths.py).
SOURCE = paths.ZONES_FILE


def find_mt4_common_files() -> Path | None:
    """Ищет папку Common/Files от MetaTrader 4/5."""
    result = paths.find_mt_common_files()
    if result:
        print(f"[sync] Found MT Common/Files: {result}")
    return result


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


def zone_file_targets() -> list[Path]:
    """Все папки, откуда индикатор может прочитать зоны.

    Кроме общей Common/Files раскладываем файл и в локальные MQL4/MQL5 Files
    каждого терминала: если общая папка недоступна (портативная установка,
    права), индикатор всё равно найдёт свежий JSON.
    """
    targets: list[Path] = []
    common = paths.find_mt_common_files()
    if common:
        targets.append(common)
    for term_type, term_path in paths.find_all_terminals():
        targets.append(term_path / ("MQL5" if term_type == "MT5" else "MQL4") / "Files")
    return targets


def sync_file(source: Path) -> bool:
    """Копирует произвольный файл во все папки Files терминалов MT4/MT5."""
    if not source.exists():
        print(f"[sync] Source file not found: {source}")
        return False

    copied = 0
    for target_dir in zone_file_targets():
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target_dir / source.name)
            print(f"[sync] Copied {source.name} to: {target_dir}")
            copied += 1
        except OSError as e:
            print(f"[sync] WARN: could not copy {source.name} to {target_dir}: {e}")

    if not copied:
        print(f"[sync] ERROR: no MetaTrader Files folder found — {source.name} "
              "not delivered, indicator will keep showing old data.")
    return copied > 0


def sync_zones():
    """Копирует zones_output.json во все папки Files терминалов MT4/MT5."""
    if not SOURCE.exists():
        print(f"[sync] Run bridge_server.py first!")
    return sync_file(SOURCE)


def find_all_terminals() -> list[tuple[str, Path]]:
    """Находит ВСЕ установленные терминалы MT4 и MT5 (по хэш-папкам)."""
    return paths.find_all_terminals()


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
        except (UnicodeDecodeError, OSError) as e:
            print(f"[install] WARN: Could not read origin.txt for {terminal_path.name}: {e}")
    
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


def copy_over_locked(src: Path, dest: Path) -> bool:
    """Копирует файл, обходя блокировку запущенным терминалом.

    MetaTrader держит загруженные .ex4/.ex5 открытыми, и обычное копирование
    падает с PermissionError — новая сборка не доезжала до терминала вообще.
    Переименовать заблокированный файл Windows позволяет, поэтому старый
    бинарник отводим в сторону и кладём новый на его место.
    """
    try:
        shutil.copy2(src, dest)
        return True
    except PermissionError:
        backup = dest.with_suffix(dest.suffix + ".old")
        try:
            if backup.exists():
                backup.unlink()
            dest.rename(backup)
            shutil.copy2(src, dest)
            print(f"  [OK] {dest.name} replaced (terminal held old file, "
                  "restart terminal to load it)")
            return True
        except OSError as e:
            print(f"  [FAIL] {dest.name} is locked and could not be replaced: {e}")
            return False
    except OSError as e:
        print(f"  [FAIL] {dest.name}: {e}")
        return False


def deploy_component(src_mq: Path, dest_dir: Path, term_path: Path, is_mt5: bool):
    """Копирует исходник (.mq4/.mq5) и, если рядом лежит уже скомпилированный
    .ex4/.ex5, копирует и его — тогда клиенту не нужен MetaEditor. Компилируем
    через metaeditor только если готового .ex-файла нет."""
    dest = dest_dir / src_mq.name
    if copy_over_locked(src_mq, dest):
        print(f"  [OK] {src_mq.stem} -> {dest.name}")

    ex_src = src_mq.with_suffix(".ex5" if is_mt5 else ".ex4")
    if ex_src.exists():
        ex_dest = dest_dir / ex_src.name
        if copy_over_locked(ex_src, ex_dest):
            # Размер и дата: по логу видно, встал ли новый бинарник или
            # терминал продолжает работать со старым.
            stat = ex_dest.stat()
            stamp = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
            print(f"  [OK] precompiled -> {ex_src.name} "
                  f"({stat.st_size} bytes, {stamp})")
        return
    compile_mq(dest, term_path, is_mt5)


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
    
    print(f"[install] Found {len(terminals)} MetaTrader terminal(s), "
          f"deploying build v{version.app_version()}")

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
                deploy_component(indicator_src, ind_dir, term_path, False)

            # --- MT4 EA ---
            ea_dir = term_path / "MQL4" / "Experts"
            if ea_dir.exists() and ea_src.exists():
                deploy_component(ea_src, ea_dir, term_path, False)

            installed += 1
            
        elif term_type == "MT5":
            indicator_src = base / "mql" / "MT5" / "Indicators" / "StrongZones.mq5"
            ea_src = base / "mql" / "MT5" / "Experts" / "SmartZonesCollector.mq5"

            # --- MT5 Индикатор ---
            ind_dir = term_path / "MQL5" / "Indicators"
            if ind_dir.exists() and indicator_src.exists():
                deploy_component(indicator_src, ind_dir, term_path, True)

            # --- MT5 EA (брокерские данные → CSV) ---
            ea_dir = term_path / "MQL5" / "Experts"
            if ea_dir.exists() and ea_src.exists():
                deploy_component(ea_src, ea_dir, term_path, True)

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

