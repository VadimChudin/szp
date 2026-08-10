"""Тесты version.py — номер сборки, который видят клиент и лог."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import version


class TestAppVersion:
    def test_reads_build_version_file(self, tmp_path, monkeypatch):
        (tmp_path / "build_version.txt").write_text("1.5\n", encoding="utf-8")
        monkeypatch.setattr(version, "_base_dir", lambda: tmp_path)
        assert version.app_version() == "1.5"

    def test_missing_file_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setattr(version, "_base_dir", lambda: tmp_path)
        assert version.app_version() == version.FALLBACK

    def test_empty_file_falls_back(self, tmp_path, monkeypatch):
        (tmp_path / "build_version.txt").write_text("  \n", encoding="utf-8")
        monkeypatch.setattr(version, "_base_dir", lambda: tmp_path)
        assert version.app_version() == version.FALLBACK
