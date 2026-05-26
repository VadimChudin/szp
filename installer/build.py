"""
build.py — Сборка Smart Zones Pro в .exe
Запуск: python build.py
"""
import subprocess
import sys
import os

SPEC_FILE = os.path.join(os.path.dirname(__file__), "SmartZonesPro.spec")
WORK_DIR = os.path.join(os.path.dirname(__file__), "build")
DIST_DIR = os.path.join(os.path.dirname(__file__), "build", "dist")

print("=" * 55)
print("  Smart Zones Pro — Build Script")
print("=" * 55)
print()

# Шаг 1: PyInstaller
print("[1/2] Building .exe with PyInstaller...")
cmd = [
    sys.executable, "-m", "PyInstaller",
    "--distpath", DIST_DIR,
    "--workpath", os.path.join(WORK_DIR, "temp"),
    "--noconfirm",
    SPEC_FILE,
]
result = subprocess.run(cmd, cwd=os.path.dirname(__file__))
if result.returncode != 0:
    print("\n[ERROR] PyInstaller failed!")
    sys.exit(1)

print(f"\n[OK] .exe built successfully!")
print(f"     Output: {DIST_DIR}\\SmartZonesPro\\SmartZonesPro.exe")

# Шаг 2: Inno Setup (если установлен)
print("\n[2/2] Looking for Inno Setup compiler...")
iscc_paths = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
    r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
]

iscc = None
for p in iscc_paths:
    if os.path.exists(p):
        iscc = p
        break

if iscc:
    print(f"  Found: {iscc}")
    iss_file = os.path.join(os.path.dirname(__file__), "setup.iss")
    result = subprocess.run([iscc, iss_file])
    if result.returncode == 0:
        print(f"\n[OK] Installer created!")
        print(f"     Output: {os.path.dirname(__file__)}\\output\\SmartZonesPro_Setup_v1.0.exe")
    else:
        print("[WARN] Inno Setup compilation failed")
else:
    print("  Inno Setup not found. Skipping installer creation.")
    print("  You can install it from: https://jrsoftware.org/isinfo.php")
    print(f"  Then run: ISCC.exe \"{os.path.dirname(__file__)}\\setup.iss\"")

print("\n" + "=" * 55)
print("  Build complete!")
print("=" * 55)
