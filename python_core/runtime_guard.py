"""Small cross-platform ownership guard for the single Bridge writer."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


class BridgeAlreadyRunning(RuntimeError):
    pass


class BridgeLock:
    """Own a lock file atomically for the lifetime of one Bridge process."""

    def __init__(self, path: Path, *, build: str) -> None:
        self.path = Path(path)
        self.build = build
        self.acquired = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({
            "pid": os.getpid(),
            "build": self.build,
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            try:
                owner = self.path.read_text(encoding="utf-8")
            except OSError:
                owner = "unknown owner"
            raise BridgeAlreadyRunning(f"Bridge writer lock exists: {owner}") from exc
        try:
            os.write(fd, payload.encode("utf-8"))
        finally:
            os.close(fd)
        self.acquired = True

    def release(self) -> None:
        if self.acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self.acquired = False

    def __enter__(self) -> "BridgeLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
