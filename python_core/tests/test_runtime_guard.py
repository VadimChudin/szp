import pytest

from runtime_guard import BridgeAlreadyRunning, BridgeLock


def test_only_one_bridge_writer_can_hold_the_lock(tmp_path):
    path = tmp_path / "bridge_writer.lock"
    first = BridgeLock(path, build="exp-test")
    first.acquire()
    try:
        with pytest.raises(BridgeAlreadyRunning):
            BridgeLock(path, build="exp-second").acquire()
    finally:
        first.release()
    assert not path.exists()


def test_released_bridge_lock_can_be_reacquired(tmp_path):
    path = tmp_path / "bridge_writer.lock"
    with BridgeLock(path, build="exp-test"):
        assert path.exists()
    with BridgeLock(path, build="exp-next"):
        assert path.exists()
