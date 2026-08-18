from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_app_password_gate_is_mandatory_and_brought_to_front():
    source = (ROOT / "python_core/app_entry.py").read_text(encoding="utf-8")
    assert "if not ask_password():" in source
    assert "root.attributes(\"-topmost\", True)" in source
    assert "Protected access is mandatory" in source
    assert "SZP_REQUIRE_PASSWORD" not in source


def test_app_exposes_startup_diagnostics_and_fatal_error_log():
    source = (ROOT / "python_core/app_entry.py").read_text(encoding="utf-8")
    assert 'if "--diagnostics" in sys.argv:' in source
    assert "def run_startup_diagnostics" in source
    assert '"startup_diagnostics.json"' in source
    assert '"startup_error.log"' in source
    assert "show_fatal_startup_error" in source


def test_ci_executes_packaged_startup_diagnostics_before_installer():
    source = (ROOT / ".github/workflows/build-turnkey.yml").read_text(encoding="utf-8")
    assert "Verify packaged startup diagnostics" in source
    assert "--diagnostics" in source
    assert "startup_diagnostics.json" in source
