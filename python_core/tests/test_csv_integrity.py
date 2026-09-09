import pytest
from data_fetcher import csv_encoding, DataUnavailableError

@pytest.mark.parametrize('payload', [b'', b'\x00' * 2048])
def test_rejects_empty_or_zero_filled_csv(tmp_path, payload):
    path = tmp_path / 'XAUUSD_H4.csv'
    path.write_bytes(payload)
    with pytest.raises(DataUnavailableError, match='Invalid market CSV'):
        csv_encoding(path)

@pytest.mark.parametrize('encoding, expected', [('utf-8', 'utf-8'), ('utf-16', 'utf-16')])
def test_keeps_valid_csv_encodings(tmp_path, encoding, expected):
    path = tmp_path / 'XAUUSD_H4.csv'
    path.write_text('time,open,high,low,close\n', encoding=encoding)
    assert csv_encoding(path) == expected
