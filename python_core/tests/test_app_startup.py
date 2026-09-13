"""The tray must appear even if the bridge or MetaTrader5 DLL fails."""
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent


def test_bridge_import_happens_off_the_ui_thread():
    text = (CORE / "app_entry.py").read_text(encoding="utf-8")
    assert "target=_run_bridge" in text
    assert "daemon=False" in text
    assert "from PIL import Image, ImageDraw" in text
    assert "from PIL import Image, ImageDraw, ImageFont" not in text
    main = text.split("def main():", 1)[1]
    assert "from bridge_server import run_monitor_loop" not in main
    assert "bridge_thread.join()" in text


def test_mt5_native_dll_failure_does_not_abort_import():
    text = (CORE / "data_fetcher.py").read_text(encoding="utf-8")
    assert "except Exception as e:" in text.split("import MetaTrader5 as mt5", 1)[1][:400]
    assert "MT5_AVAILABLE = False" in text


def test_pyinstaller_lists_new_6_1_modules():
    spec = (CORE.parent / "installer" / "SmartZonesPro.spec").read_text(encoding="utf-8")
    workflow = (CORE.parent / ".github" / "workflows" / "build-turnkey.yml").read_text(encoding="utf-8")
    for name in (
        "market_data",
        "zone_confirmation",
        "zone_reaction",
        "accumulation",
        "active_zones",
        "sl_model",
    ):
        assert name in spec, name
        assert name in workflow, name
