"""Дисковый кэш тиков Dukascopy.

Регрессия, которую эти тесты закрывают: в fetch_hour стоял локальный
`import pandas as pd`, из-за чего pd становилась локальной переменной на всю
функцию, а обращение к кэшу в начале функции падало UnboundLocalError. Ошибку
глотал `except Exception`, кэш-файл удалялся, и каждый час качался заново.

Плюс кэш писался в .parquet (тянет pyarrow, 137 МБ), которого не было в
установщике — то есть у клиента кэш не работал вообще.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

import dukascopy_loader


@pytest.fixture
def loader(tmp_path, monkeypatch):
    monkeypatch.setattr(dukascopy_loader, "CACHE_DIR", tmp_path)
    return dukascopy_loader.DukascopyLoader()


DT = datetime(2026, 1, 2, 3, tzinfo=timezone.utc)


def _ticks() -> pd.DataFrame:
    return pd.DataFrame({
        "time_ms": [1767322800000],
        "time": [pd.Timestamp("2026-01-02 03:00:00", tz="UTC")],
        "ask": [2000.5],
        "bid": [2000.1],
        "ask_vol": [1.5],
        "bid_vol": [2.0],
    })


def test_cache_does_not_use_parquet(loader):
    """Расширение кэша не parquet: иначе нужен pyarrow в установщике."""
    path = loader._cache_key("XAUUSD", DT)
    assert path.suffixes[-2:] == [".csv", ".gz"]
    assert ".parquet" not in path.name


def test_cache_hit_returns_data_and_keeps_file(loader):
    """Главная регрессия: попадание в кэш возвращает данные, файл остаётся."""
    path = loader._cache_key("XAUUSD", DT)
    loader._write_cache(path, _ticks())
    assert path.exists()

    result = loader.fetch_hour("XAUUSD", DT)

    assert result is not None
    assert len(result) == 1
    assert result["ask"].iloc[0] == pytest.approx(2000.5)
    assert path.exists(), "кэш-файл не должен удаляться при успешном чтении"


def test_cache_roundtrip_preserves_columns_and_time(loader):
    path = loader._cache_key("XAUUSD", DT)
    loader._write_cache(path, _ticks())

    restored = loader._read_cache(path)

    assert list(restored.columns) == dukascopy_loader.TICK_COLUMNS
    assert pd.api.types.is_datetime64_any_dtype(restored["time"])


def test_empty_hour_is_cached_and_read_back(loader):
    """Пустой час кэшируется, чтобы не качать битые часы заново."""
    path = loader._cache_key("XAUUSD", DT)
    loader._write_cache(path, None)

    restored = loader._read_cache(path)

    assert restored.empty
    assert list(restored.columns) == dukascopy_loader.TICK_COLUMNS


def test_corrupt_cache_is_removed_and_not_returned(loader, monkeypatch):
    path = loader._cache_key("XAUUSD", DT)
    path.write_bytes(b"not a gzip csv at all")
    # Сеть в тестах недоступна: обрываем загрузку сразу после промаха кэша.
    monkeypatch.setattr(
        dukascopy_loader.urllib.request, "urlopen",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("no network")),
    )

    result = loader.fetch_hour("XAUUSD", DT)

    assert result is None
    # Битый файл заменён пустым маркером, а не оставлен как есть.
    assert loader._read_cache(path).empty


def test_fetch_hour_has_no_local_pandas_import():
    """Защита от возврата затенения pandas внутри функции."""
    import ast
    import inspect

    source = inspect.getsource(dukascopy_loader.DukascopyLoader.fetch_hour)
    tree = ast.parse(source.lstrip())
    local_imports = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        and any(a.asname == "pd" or a.name == "pandas" for a in node.names)
    ]
    assert not local_imports, "локальный import pandas снова затеняет модульный"
