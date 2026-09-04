"""
Тесты для bridge_server.py — чтение флага кнопки FP.
"""

import bridge_server


class TestReadFootprintTimeframe:
    def test_utf16_flag_from_mt5(self, tmp_path):
        """MT5 пишет флаг в UTF-16 — раньше запуск падал с embedded null."""
        flag = tmp_path / "footprint_request.flag"
        flag.write_bytes("4h".encode("utf-16"))
        assert bridge_server.read_footprint_timeframe(flag) == "4h"

    def test_plain_ansi_flag_from_mt4(self, tmp_path):
        flag = tmp_path / "footprint_request.flag"
        flag.write_text("1d")
        assert bridge_server.read_footprint_timeframe(flag) == "1d"

    def test_unknown_value_falls_back(self, tmp_path):
        flag = tmp_path / "footprint_request.flag"
        flag.write_text("garbage")
        assert bridge_server.read_footprint_timeframe(flag) == "1h"

    def test_missing_file_falls_back(self, tmp_path):
        assert bridge_server.read_footprint_timeframe(tmp_path / "nope.flag") == "1h"


class TestBridgeRuntimeSymbols:
    """Символы, которых не хватало в рантайме и это глотал широкий except.

    `pd` использовался в блоке слоя ИИ (pd.Timestamp для якоря времени), но
    pandas в модуле не импортировался: вызов падал NameError, except печатал
    «AI layer skipped», и слой ИИ вместе с защитой лицензии от отката часов
    не работал в проде вообще.
    """

    def test_pandas_is_available_for_ai_time_anchor(self):
        assert hasattr(bridge_server, "pd"), "нет модульного pandas — слой ИИ упадёт"
        assert bridge_server.pd.Timestamp("2026-01-02T03:00:00").timestamp() > 0

    def test_ai_block_uses_module_level_pandas(self):
        """В блоке ИИ pd берётся из модуля, а не из ниоткуда."""
        import ast
        import inspect

        source = inspect.getsource(bridge_server)
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    imported.add(alias.asname or alias.name.split(".")[0])
        assert "pd" in imported

    def test_footprint_entrypoint_imports_window_lazily(self):
        """`--footprint` раньше падал NameError: функция не импортировалась."""
        source = (bridge_server.Path(bridge_server.__file__)).read_text(encoding="utf-8")
        assert "from footprint_window import open_footprint_window" in source
        entry = source[source.index('elif "--footprint" in sys.argv:'):]
        assert "open_footprint_window" in entry
        # Импорт именно внутри ветки: наверху файла webview блокирует headless.
        assert source.index("from footprint_window import open_footprint_window") > \
            source.index('elif "--footprint" in sys.argv:')

    def test_ai_failure_is_logged_with_traceback(self):
        """Без трейсбека NameError жил незаметно годами."""
        source = (bridge_server.Path(bridge_server.__file__)).read_text(encoding="utf-8")
        assert "AI layer skipped" in source
        block = source[source.index("AI layer skipped"):]
        assert "traceback.print_exc()" in block[:400]
