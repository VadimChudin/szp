"""
ЛПЗС «Родина» — веб-сервер эмулятора.

Эмуляция ПЛК и установки целиком работает в браузере (frontend/js/plc.js,
frontend/js/plant.js). Сервер только раздаёт статику и отвечает на проверку
здоровья: второй, серверной модели нет, чтобы логика не расходилась с ПЛК.

    python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
FRONT = ROOT / "frontend"

app = FastAPI(title="ЛПЗС Родина — эмулятор", version="2.0.0")


@app.get("/api/health")
def health():
    """Проба для балансировщика и docker healthcheck."""
    return {"status": "ok", "frontend": (FRONT / "index.html").exists()}


@app.get("/")
def index():
    return FileResponse(FRONT / "index.html")


for sub in ("css", "js", "assets"):
    if (FRONT / sub).exists():
        app.mount("/" + sub, StaticFiles(directory=str(FRONT / sub)), name=sub)
