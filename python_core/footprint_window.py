"""
footprint_window.py — Professional Footprint Chart (TradingView-style).

Dark theme, real-time, smooth zoom/pan everywhere, Y-axis drag to scale,
Continuous candle grids to fix daily gaps, TF switching via pywebview API.
"""

import json
from pathlib import Path
import paths
from footprint_data import get_collector

ZONES_FILE = paths.ZONES_FILE
BROKERS_FILE = paths.BROKERS_FILE

def _load_zones():
    if not ZONES_FILE.exists():
        return []
    try:
        with open(ZONES_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("zones", [])
    except Exception:
        return []

def _candles_to_json(candles, interval):
    mx = 1
    for c in candles:
        for d in c.levels.values():
            mx = max(mx, d["buy"], d["sell"])

    data = []
    for c in candles:
        levels = []
        for price, d in c.levels.items():
            levels.append({"p": round(price, 2), "b": round(d["buy"], 2), "s": round(d["sell"], 2)})
        data.append({
            "t": c.time_str, "o": round(c.open, 2), "h": round(c.high, 2),
            "l": round(c.low, 2), "c": round(c.close, 2), "d": round(c.delta, 1),
            "levels": levels, "bull": c.is_bullish,
            "real": getattr(c, 'is_real', False),
            "poc": round(getattr(c, 'poc_price', (c.high + c.low) / 2), 2),
        })
    return json.dumps({"candles": data, "mx": round(mx, 2),
                        "step": candles[0].price_step, "tf": interval,
                        "zones": _load_zones()})

class API:
    def __init__(self, collector):
        self.collector = collector
        self._current_tf = "4h"

    def get_data(self, tf=None):
        if tf:
            self._current_tf = tf
        candles = self.collector.get_footprint(self._current_tf)
        if not candles:
            return json.dumps({"candles": [], "mx": 1, "step": 1, "tf": self._current_tf, "zones": []})
        return _candles_to_json(candles, self._current_tf)

    def refresh(self):
        """Полная перезагрузка данных текущего TF из MT5."""
        buf = self.collector.buffers.get(self._current_tf)
        if buf:
            try:
                # Полная перезагрузка — свежие данные с нуля
                count = buf.load_initial()
                print(f"[footprint] Refresh: reloaded {count} candles for {self._current_tf}")
            except Exception as e:
                print(f"[footprint] Refresh error: {e}")
                # Fallback на инкрементальный апдейт
                buf.update()
        return self.get_data()

    def get_brokers(self):
        try:
            if BROKERS_FILE.exists():
                with open(BROKERS_FILE, "r", encoding="utf-8") as f:
                    return f.read()
        except Exception:
            pass
        return json.dumps({"active_broker": 0, "brokers": []})

    def save_brokers(self, config_str):
        try:
            data = json.loads(config_str)
            BROKERS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(BROKERS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            return True
        except Exception:
            return False

HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Smart Zones Pro — Footprint</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; user-select:none; }
body { background:#131722; overflow:hidden; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; color:#d1d4dc; }
#toolbar {
  height:42px; background:#1e222d; display:flex; align-items:center;
  padding:0 12px; gap:8px; border-bottom:1px solid #2a2e39; font-size:13px;
}
#toolbar .logo { font-weight:700; color:#2962ff; letter-spacing:0.5px; }
#toolbar .sep { width:1px; height:22px; background:#363a45; margin:0 4px; }
.tf-btn {
  padding:5px 14px; border:1px solid #363a45; border-radius:4px; cursor:pointer;
  font-size:12px; font-weight:600; background:transparent; color:#787b86;
  transition: all 0.15s;
}
.tf-btn:hover { color:#d1d4dc; border-color:#505565; }
.tf-btn.active { background:#2962ff; color:white; border-color:#2962ff; }
.nav-btn {
  padding:4px 10px; border:1px solid #363a45; border-radius:4px; cursor:pointer;
  font-size:14px; background:transparent; color:#787b86; transition:all 0.15s;
}
.nav-btn:hover { color:#d1d4dc; background:#2a2e39; }
#info { margin-left:auto; font-size:12px; color:#787b86; font-family:'Courier New',monospace; font-weight:bold; }
#status { font-size:11px; color:#089981; margin-left:8px; }
canvas { display:block; cursor:crosshair; }
#auto-btn {
  position:absolute; bottom:80px; right:12px; background:#1e222d; border:1px solid #363a45;
  color:#d1d4dc; border-radius:4px; padding:4px 8px; font-size:11px; cursor:pointer;
  box-shadow: 0 2px 4px rgba(0,0,0,0.2); transition: 0.1s; display:none;
}
#auto-btn:hover { background:#2a2e39; }
/* Modal Styles */
.modal-overlay {
  position: fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.6);
  display:none; align-items:center; justify-content:center; z-index:999;
}
.modal {
  background:#1e222d; border-radius:8px; border:1px solid #363a45; width:450px;
  padding:20px; box-shadow: 0 10px 30px rgba(0,0,0,0.5);
}
.modal h2 { color:#d1d4dc; font-size:16px; margin-bottom:15px; border-bottom:1px solid #2a2e39; padding-bottom:10px; }
.broker-slot { margin-bottom:15px; padding:10px; border:1px solid #2a2e39; border-radius:6px; background:#131722; position:relative;}
.broker-slot.active { border-color:#089981; }
.broker-slot input {
  display:block; width:100%; padding:5px 8px; margin-bottom:5px;
  background:#1e222d; border:1px solid #363a45; color:#d1d4dc; border-radius:4px;
}
.broker-slot label { font-size:10px; color:#787b86; display:block; margin-bottom:2px; }
.btn-row { display:flex; justify-content:space-between; margin-top:20px; }
.btn-save { background:#2962ff; color:white; border:none; padding:8px 16px; border-radius:4px; cursor:pointer; font-weight:bold; }
.btn-save:hover { background:#1e53e5; }
.btn-close { background:transparent; color:#787b86; border:1px solid #363a45; padding:8px 16px; border-radius:4px; cursor:pointer; }
.btn-close:hover { background:#2a2e39; color:white; }
.btn-activate { position:absolute; top:10px; right:10px; background:#089981; color:white; border:none; padding:4px 8px; border-radius:4px; font-size:10px; cursor:pointer; }
.btn-activate:hover { opacity:0.8; }
</style>
</head>
<body>
<div id="toolbar">
  <span class="logo">⚡ FOOTPRINT</span>
  <span class="sep"></span>
  <button class="tf-btn" data-tf="1h" onclick="switchTF('1h')">1H</button>
  <button class="tf-btn active" data-tf="4h" onclick="switchTF('4h')">4H</button>
  <button class="tf-btn" data-tf="1d" onclick="switchTF('1d')">1D</button>
  <span class="sep"></span>
  <button class="nav-btn" onclick="sc(-10)" title="Home">⏮</button>
  <button class="nav-btn" onclick="sc(-3)">◀</button>
  <button class="nav-btn" onclick="sc(3)">▶</button>
  <button class="nav-btn" onclick="sc(10)" title="End">⏭</button>
  <span class="sep"></span>
  <button class="nav-btn" onclick="zm(-2)" title="Zoom In">🔍+</button>
  <button class="nav-btn" onclick="zm(2)" title="Zoom Out">🔍−</button>
  <span class="sep"></span>
  <button class="nav-btn" onclick="refreshData()" title="Refresh" style="color:#089981">⟳</button>
  <button class="nav-btn" onclick="openSettings()" title="Data Center (MT5 Brokers)">⚙</button>
  <span id="status">●</span>
  <span id="info">Loading...</span>
</div>
<canvas id="c"></canvas>
<button id="auto-btn" onclick="resetAutoScale()">Auto (A)</button>

<div id="settings-modal" class="modal-overlay">
  <div class="modal">
    <h2>Data Center (MT5 Brokers)</h2>
    <div id="brokers-container"></div>
    <div class="btn-row">
      <button class="btn-close" onclick="closeSettings()">Cancel</button>
      <button class="btn-save" onclick="saveSettings()">Save Configuration</button>
    </div>
  </div>
</div>

<script>
let DATA = null;
let W, H;
let scrollPos = 0;
let visibleCount = 14;
let currentTF = '4h';

// Y-Scale logic
let autoScaleY = true;
let currentMinP = 0, currentMaxP = 1;

// Mouse interaction
let dragX = null, dragStartY = null;
let isDraggingY = false;
let mouseX = -1, mouseY = -1;

const canvas = document.getElementById('c');
const ctx = canvas.getContext('2d');
const autoBtn = document.getElementById('auto-btn');

async function loadData(tf) {
  try {
    document.getElementById('status').style.color = '#ff9800';
    document.getElementById('status').textContent = '◌';
    const raw = await pywebview.api.get_data(tf || currentTF);
    DATA = JSON.parse(raw);
    currentTF = DATA.tf || currentTF;
    scrollPos = Math.max(0, DATA.candles.length - visibleCount);
    autoScaleY = true;
    draw();
    document.getElementById('status').style.color = '#089981';
    document.getElementById('status').textContent = '●';
  } catch(e) { console.error('Load error:', e); }
}

async function refreshData() {
  try {
    document.getElementById('status').textContent = '↻';
    const raw = await pywebview.api.refresh();
    const newDATA = JSON.parse(raw);
    
    let wasAtEnd = false;
    if (DATA) {
        const maxScroll = Math.max(0, DATA.candles.length - Math.floor(visibleCount * 0.2));
        if (scrollPos >= maxScroll - 1) {
            wasAtEnd = true;
        }
    } else {
        wasAtEnd = true;
    }
    
    DATA = newDATA;
    if (wasAtEnd) {
        scrollPos = Math.max(0, DATA.candles.length - Math.floor(visibleCount * 0.2));
    }
    
    draw();
    document.getElementById('status').style.color = '#089981';
    document.getElementById('status').textContent = '●';
  } catch(e) { console.error(e); }
}

function switchTF(tf) {
  currentTF = tf;
  document.querySelectorAll('.tf-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.tf === tf));
  loadData(tf);
}

function resetAutoScale() {
  autoScaleY = true;
  draw();
}

// Автообновление каждые 10 секунд (инкрементальный апдейт через update())
let autoRefreshId = null;
function startAutoRefresh() {
  if (autoRefreshId) clearInterval(autoRefreshId);
  autoRefreshId = setInterval(async () => {
    try {
      const raw = await pywebview.api.get_data(); // get_data без аргумента = текущий TF, без перезагрузки
      const newDATA = JSON.parse(raw);
      
      let wasAtEnd = false;
      if (DATA) {
          const maxScroll = Math.max(0, DATA.candles.length - Math.floor(visibleCount * 0.2));
          if (scrollPos >= maxScroll - 1) wasAtEnd = true;
      } else {
          wasAtEnd = true;
      }
      
      DATA = newDATA;
      if (wasAtEnd) {
          scrollPos = Math.max(0, DATA.candles.length - Math.floor(visibleCount * 0.2));
      }
      draw();
    } catch(e) {}
  }, 10000);
}

function resize() {
  W = window.innerWidth;
  H = window.innerHeight - 42;
  canvas.width = W; canvas.height = H;
  if (DATA) draw();
}

function draw() {
  if (!DATA || !DATA.candles.length) return;
  
  autoBtn.style.display = autoScaleY ? 'none' : 'block';
  ctx.clearRect(0, 0, W, H);

  const candles = DATA.candles;
  const n = candles.length;
  const step = DATA.step;
  const mx = DATA.mx;

  const s = Math.max(0, scrollPos);
  const e = Math.min(s + visibleCount, n);
  const vis = candles.slice(s, e);
  if (!vis.length) return;

  // Рассчитываем Auto Bounds для видимых свечей
  let visMinP = Infinity, visMaxP = -Infinity;
  vis.forEach(c => {
    if (c.l < visMinP) visMinP = c.l;
    if (c.h > visMaxP) visMaxP = c.h;
  });
  visMinP -= step * 3; visMaxP += step * 3;

  if (autoScaleY) {
    currentMinP = visMinP;
    currentMaxP = visMaxP;
  }

  const minP = currentMinP;
  const maxP = currentMaxP;
  
  const priceAxisW = 72;
  const chartW = W - priceAxisW;
  const chartH = H * 0.82;
  const deltaH = H * 0.14;
  const deltaY0 = chartH + H * 0.04;

  const colW = chartW / visibleCount; // Фиксируем ширину колонки, чтобы можно было скроллить "в пустоту"
  const halfW = colW * 0.35;
  const bodyW = colW * 0.10;
  const gapW = colW * 0.03;
  const ml = 6;

  // py(p) возвращает пиксельную Y-координату для цены p
  const py = (p) => chartH * (1 - (p - minP) / (maxP - minP));
  // cellH это высота одной ячейки в пикселях
  const cellH = (step / (maxP - minP)) * chartH;

  const bgCol = '#131722';
  const gridCol = '#2a2e39';
  const textCol = '#787b86';

  // === Background ===
  ctx.fillStyle = bgCol;
  ctx.fillRect(0, 0, W, H);

  // === Grid ===
  const priceGridStep = step * Math.max(1, Math.round(5 / Math.max(1, cellH / 15)));
  let gp = Math.ceil(minP / priceGridStep) * priceGridStep;
  ctx.strokeStyle = gridCol; ctx.lineWidth = 0.5;
  ctx.font = '11px Courier New'; ctx.fillStyle = textCol; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
  while (gp <= maxP) {
    const gy = py(gp);
    ctx.beginPath(); ctx.moveTo(ml, gy); ctx.lineTo(chartW, gy); ctx.stroke();
    ctx.fillText(gp.toFixed(2), W - 6, gy);
    gp += priceGridStep;
  }

  // === Зоны (SZP) — золотой полупрозрачный фон + бейдж со score ===
  const zonesList = DATA.zones || [];
  zonesList.forEach(z => {
    // Границы зоны: top/bottom если есть, иначе ±1 пункт вокруг price.
    const zTop = (z.top    !== undefined && z.top    !== null) ? z.top    : (z.price + 1);
    const zBot = (z.bottom !== undefined && z.bottom !== null) ? z.bottom : (z.price - 1);
    const yTop = py(Math.max(zTop, zBot));
    const yBot = py(Math.min(zTop, zBot));
    const zh   = Math.max(2, Math.abs(yBot - yTop));
    const zy   = py((zTop + zBot) / 2);

    const score = z.score || 0;

    // Цвет: золотой по умолчанию (зона = премиум-сигнал),
    // bull/bear оттенки если есть лейбл.
    let bgFill   = 'rgba(255,215,0,0.10)';   // gold @ 10%
    let edgeCol  = 'rgba(255,215,0,0.55)';
    let textCol2 = '#ffd700';
    if (z.label && z.label.includes('Bull')) {
      bgFill   = 'rgba(8,153,129,0.14)';
      edgeCol  = 'rgba(8,153,129,0.70)';
      textCol2 = '#089981';
    } else if (z.label && z.label.includes('Bear')) {
      bgFill   = 'rgba(242,54,69,0.14)';
      edgeCol  = 'rgba(242,54,69,0.70)';
      textCol2 = '#f23645';
    }

    // Полупрозрачная заливка по всей ширине графика
    ctx.fillStyle = bgFill;
    ctx.fillRect(ml, yTop, chartW - ml, zh);

    // Верхняя и нижняя граница зоны
    ctx.strokeStyle = edgeCol;
    ctx.lineWidth = score >= 11 ? 1.5 : 1;
    ctx.setLineDash([6, 4]);
    ctx.beginPath(); ctx.moveTo(ml, yTop); ctx.lineTo(chartW, yTop); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(ml, yBot); ctx.lineTo(chartW, yBot); ctx.stroke();
    ctx.setLineDash([]);

    // Подпись зоны + бейдж score (справа у верхней границы)
    const label = (z.label || 'ZONE') + '  S:' + score;
    ctx.font = 'bold 10px Courier New';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    const padX = 6, padY = 3;
    const txtW = ctx.measureText(label).width;
    const badgeX = chartW - 6 - txtW - padX * 2;
    const badgeY = yTop + 1;
    const badgeH = 16;
    ctx.fillStyle = 'rgba(20,22,30,0.85)';
    ctx.fillRect(badgeX, badgeY, txtW + padX * 2, badgeH);
    ctx.strokeStyle = edgeCol;
    ctx.lineWidth = 1;
    ctx.strokeRect(badgeX, badgeY, txtW + padX * 2, badgeH);
    ctx.fillStyle = textCol2;
    ctx.fillText(label, chartW - 6 - padX, badgeY + badgeH / 2);
  });

  // === Свечи (Непрерывная сетка) ===
  vis.forEach((candle, j) => {
    const xBase = ml + j * colW;
    const xBuyL = xBase + colW * 0.04;
    const xMid = xBuyL + halfW;
    const xSellR = xMid + halfW;
    const xBody = xSellR + gapW;

    // Быстрый доступ к уровням
    const volMap = {};
    candle.levels.forEach(l => { volMap[l.p.toFixed(2)] = l; });

    // Диапазон ячеек текущей свечи (используем floor для нижнего края ячейки)
    const startP = Math.floor(candle.l / step) * step;
    const endP = Math.floor(candle.h / step) * step;

    let maxT = 0, maxPr = null, minT = Infinity, minPr = null;
    let lvlsCount = 0;
    let candleMaxSide = 1; // Максимальный объем (buy или sell) внутри ЭТОЙ свечи
    
    // 1-й проход: ищем Макс и Мин
    for (let p = startP; p <= endP + step * 0.1; p += step) {
      const l = volMap[p.toFixed(2)];
      if (l) {
        const t = l.b + l.s;
        if (t > maxT) { maxT = t; maxPr = p; }
        if (t < minT && t > 0.1) { minT = t; minPr = p; }
        if (l.b > candleMaxSide) candleMaxSide = l.b;
        if (l.s > candleMaxSide) candleMaxSide = l.s;
      }
      lvlsCount++;
    }

    // 2-й проход: рисуем все ячейки
    for (let p = startP; p <= endP + step * 0.1; p += step) {
      const l = volMap[p.toFixed(2)];
      const buy = l ? l.b : 0;
      const sell = l ? l.s : 0;
      
      const yTop = py(p + step);
      const yBot = py(p);
      const h = Math.abs(yBot - yTop);

      // POC cell — золотой full-fill фон под ячейкой максимального объёма
      const isPocCell = (maxPr !== null && Math.abs(p - maxPr) < step * 0.1 && maxT > mx * 0.1);
      if (isPocCell) {
        ctx.fillStyle = 'rgba(255,215,0,0.55)'; // густое золото
        ctx.fillRect(xBuyL, yTop, halfW * 2, h);
      }

      // Рамки
      ctx.strokeStyle = 'rgba(60,65,80,1)';
      ctx.lineWidth = 0.5;
      ctx.strokeRect(xBuyL, yTop, halfW, h);
      ctx.strokeRect(xMid, yTop, halfW, h);

      // Buy fill (089981) - Линейно пропорционально ширине ячейки
      if (buy > 0) {
        // Минимальная видимая толщина 2 пикселя
        const fw = Math.max(2, halfW * (buy / candleMaxSide)); 
        ctx.fillStyle = 'rgba(8,153,129, 0.8)'; // Густой цвет
        ctx.fillRect(xBuyL, yTop, fw, h);
      }

      // Sell fill (f23645) - Линейно пропорционально ширине ячейки
      if (sell > 0) {
        const fw = Math.max(2, halfW * (sell / candleMaxSide));
        ctx.fillStyle = 'rgba(242,54,69, 0.8)';
        ctx.fillRect(xSellR - fw, yTop, fw, h);
      }

      // 🟡 Макс объём
      if (Math.abs(p - maxPr) < step*0.1 && maxT > mx * 0.1) {
        ctx.strokeStyle = '#ffcc00'; ctx.lineWidth = 2;
        ctx.strokeRect(xBuyL, yTop, halfW * 2, h);
      }
      
      // 🔵 Мин объём
      if (Math.abs(p - minPr) < step*0.1 && minPr !== maxPr && lvlsCount > 2) {
        ctx.strokeStyle = '#2196f3'; ctx.lineWidth = 1.5;
        ctx.strokeRect(xBuyL, yTop, halfW * 2, h);
      }

      // Текст только если высота ячейки достаточна
      const fs = Math.max(0, Math.min(12, h * 0.6));
      if (fs >= 6) {
        const ty = yTop + h/2;
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        if (buy > 0) {
          ctx.font = `${buy > candleMaxSide * 0.5 ? 'bold ' : ''}${fs}px Courier New`;
          ctx.fillStyle = buy > candleMaxSide * 0.5 ? '#ffffff' : '#a3a6af';
          const txt = buy >= 10 ? Math.round(buy).toString() : buy.toFixed(1);
          ctx.fillText(txt, xBuyL + halfW/2, ty);
        }
        if (sell > 0) {
          ctx.font = `${sell > candleMaxSide * 0.5 ? 'bold ' : ''}${fs}px Courier New`;
          ctx.fillStyle = sell > candleMaxSide * 0.5 ? '#ffffff' : '#a3a6af';
          const txt = sell >= 10 ? Math.round(sell).toString() : sell.toFixed(1);
          ctx.fillText(txt, xMid + halfW/2, ty);
        }
      }
    }

    // Тело свечи сбоку (TradingView colors)
    const bullCol = '#089981'; const bearCol = '#f23645';
    const colCol = candle.bull ? bullCol : bearCol;

    ctx.strokeStyle = colCol; ctx.lineWidth = 1.5; ctx.globalAlpha = 1.0;
    ctx.beginPath();
    ctx.moveTo(xBody + bodyW/2, py(candle.h));
    ctx.lineTo(xBody + bodyW/2, py(candle.l));
    ctx.stroke();

    ctx.fillStyle = colCol;
    const oY = py(candle.o), cY = py(candle.c);
    ctx.fillRect(xBody, Math.min(oY, cY), bodyW, Math.max(3, Math.abs(cY - oY)));

    // LIVE indicator: зелёная точка если данные реальные (из тиков)
    if (candle.real) {
      ctx.fillStyle = '#00e676';
      ctx.beginPath();
      ctx.arc(xMid, py(candle.h) - 6, 3, 0, Math.PI * 2);
      ctx.fill();
    }

    // POC line (Point of Control) — оранжевая пунктирная линия
    if (candle.poc && candle.poc >= candle.l && candle.poc <= candle.h) {
      const pocY = py(candle.poc);
      ctx.strokeStyle = '#FF9800';
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(xBuyL, pocY);
      ctx.lineTo(xSellR, pocY);
      ctx.stroke();
      ctx.setLineDash([]);

      // Подпись POC справа
      ctx.font = '9px Courier New';
      ctx.fillStyle = '#FF9800';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText('POC ' + candle.poc.toFixed(0), xSellR + 2, pocY);
    }
  });

  // === Дельта ===
  const maxD = Math.max(1, ...vis.map(c => Math.abs(c.d)));
  ctx.fillStyle = bgCol;
  ctx.fillRect(0, deltaY0 - 2, W, deltaH + 4);
  ctx.strokeStyle = gridCol; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(0, deltaY0); ctx.lineTo(W, deltaY0); ctx.stroke();

  const dMid = deltaY0 + deltaH / 2;
  ctx.strokeStyle = '#363c4e'; ctx.lineWidth = 0.5;
  ctx.beginPath(); ctx.moveTo(ml, dMid); ctx.lineTo(chartW, dMid); ctx.stroke();

  vis.forEach((c, j) => {
    const x = ml + j * colW + colW * 0.12;
    const bw = colW * 0.76;
    const bh = (Math.abs(c.d) / maxD) * (deltaH / 2 - 6);
    ctx.fillStyle = c.d >= 0 ? '#089981' : '#f23645';
    ctx.fillRect(x, c.d >= 0 ? dMid - bh : dMid, bw, bh);
  });

  ctx.font = '10px Courier New'; ctx.fillStyle = textCol; ctx.textAlign = 'center';
  vis.forEach((c, j) => {
    const x = ml + j * colW + colW/2;
    const t = c.t.split(' ');
    ctx.fillText(t.length > 1 ? t[1].slice(0,5) : t[0].slice(5,10), x, deltaY0 + deltaH - 3);
  });

  // === Price Axis Bar ===
  ctx.fillStyle = bgCol;
  ctx.fillRect(chartW, 0, priceAxisW, H);
  ctx.strokeStyle = '#2a2e39'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(chartW, 0); ctx.lineTo(chartW, chartH); ctx.stroke();

  gp = Math.ceil(minP / priceGridStep) * priceGridStep;
  ctx.font = '11px Courier New'; ctx.fillStyle = textCol; ctx.textAlign = 'right'; ctx.textBaseline='middle';
  while (gp <= maxP) {
    ctx.fillText(gp.toFixed(2), W - 6, py(gp));
    gp += priceGridStep;
  }

  // === Crosshair ===
  if (mouseX > ml && mouseX < chartW && mouseY > 0 && mouseY < chartH) {
    ctx.strokeStyle = 'rgba(120,123,134,0.4)';
    ctx.lineWidth = 0.5; ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(mouseX, 0); ctx.lineTo(mouseX, chartH); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(ml, mouseY); ctx.lineTo(chartW, mouseY); ctx.stroke();
    ctx.setLineDash([]);

    const crossPrice = minP + (1 - mouseY / chartH) * (maxP - minP);
    ctx.fillStyle = '#2962ff';
    ctx.fillRect(chartW + 2, mouseY - 10, priceAxisW - 2, 20);
    ctx.fillStyle = 'white'; ctx.font = 'bold 11px Courier New';
    ctx.fillText(crossPrice.toFixed(2), W - 6, mouseY);
  }

  // Info Text
  const last = candles[candles.length - 1];
  const chg = last.c - candles[Math.max(0, candles.length-2)].o;
  document.getElementById('info').textContent =
    `XAUUSD (MT4) · ${currentTF.toUpperCase()} - Last: $${last.c.toFixed(2)} ` +
    ` ${chg >= 0 ? '+' : ''}${chg.toFixed(2)} - ${s+1}–${e}/${n}`;
}

// ── Интерактив ──
function sc(d) {
  if (!DATA) return;
  // Максимальный скролл теперь позволяет уходить "вправо" за пределы графика (до 80% от видимого окна)
  const maxScroll = Math.max(0, DATA.candles.length - Math.floor(visibleCount * 0.2));
  scrollPos = Math.max(0, Math.min(maxScroll, scrollPos + d));
  draw();
}
function zm(d) {
  visibleCount = Math.max(3, Math.min(80, visibleCount + d));
  if (DATA) { 
    const maxScroll = Math.max(0, DATA.candles.length - Math.floor(visibleCount * 0.2));
    scrollPos = Math.min(scrollPos, maxScroll); 
    draw(); 
  }
}

canvas.addEventListener('mousedown', e => {
  const rect = canvas.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  
  if (x > W - 72 && y < H * 0.82) { // Y-Axis
    isDraggingY = true;
    dragStartY = y;
    autoScaleY = false;
    canvas.style.cursor = 'ns-resize';
  } else {                          // Chart
    dragX = x;
    dragStartY = y;
    canvas.style.cursor = 'grabbing';
  }
});

canvas.addEventListener('mousemove', e => {
  const rect = canvas.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  mouseX = x; mouseY = y;

  if (isDraggingY) {
    const dy = y - dragStartY;
    dragStartY = y;
    const range = currentMaxP - currentMinP;
    
    // Scale (Zoom Y)
    const zoomFactor = Math.exp(dy * 0.01);
    const priceHover = currentMaxP - (y / (H * 0.82)) * range;
    currentMinP = priceHover - (priceHover - currentMinP) * zoomFactor;
    currentMaxP = priceHover + (currentMaxP - priceHover) * zoomFactor;
    draw();

  } else if (dragX !== null) {
    const dx = x - dragX;
    const dy = y - dragStartY;

    // Pan X
    const s = Math.round(dx / 30);
    if (s) { dragX = x; sc(-s); }

    // Pan Y
    if (!autoScaleY && Math.abs(dy) > 0) {
      const range = currentMaxP - currentMinP;
      const shift = (dy / (H * 0.82)) * range;
      currentMinP += shift;
      currentMaxP += shift;
      dragStartY = y;
      draw();
    } else if (autoScaleY) { draw(); }

  } else {
    if (DATA) draw();
  }
});

canvas.addEventListener('mouseup', () => { isDraggingY = false; dragX = null; canvas.style.cursor = 'crosshair'; });
canvas.addEventListener('mouseleave', () => { isDraggingY = false; dragX = null; mouseX = mouseY = -1; if(DATA) draw(); });

canvas.addEventListener('dblclick', e => {
  if (e.clientX > W - 72) resetAutoScale();
});

canvas.addEventListener('wheel', e => {
  e.preventDefault();
  zm(e.deltaY > 0 ? 1 : -1);
}, {passive: false});

document.addEventListener('keydown', e => {
  switch(e.key) {
    case 'ArrowLeft': sc(-2); break;
    case 'ArrowRight': sc(2); break;
    case '+': case '=': zm(-2); break;
    case '-': zm(2); break;
    case 'Home': scrollPos = 0; draw(); break;
    case 'End': if(DATA) { scrollPos = DATA.candles.length - visibleCount; draw(); } break;
  }
});

window.addEventListener('resize', resize);

let brokersData = { active_broker: 0, brokers: [] };

async function openSettings() {
  const resp = await pywebview.api.get_brokers();
  brokersData = JSON.parse(resp);
  const container = document.getElementById('brokers-container');
  container.innerHTML = '';
  
  brokersData.brokers.forEach((b, i) => {
    const isActive = (brokersData.active_broker === i);
    container.innerHTML += `
      <div class="broker-slot ${isActive ? 'active' : ''}">
        ${!isActive ? `<button class="btn-activate" onclick="activateBroker(${i})">SET ACTIVE</button>` : `<span style="position:absolute;top:10px;right:10px;color:#089981;font-size:11px;font-weight:bold;">● ACTIVE</span>`}
        <label>Broker Name</label>
        <input type="text" id="b-name-${i}" value="${b.name}">
        <div style="display:flex;gap:5px;">
           <div style="flex:1"><label>Server</label><input type="text" id="b-srv-${i}" value="${b.server}"></div>
           <div style="flex:1"><label>Login</label><input type="text" id="b-log-${i}" value="${b.login}"></div>
        </div>
        <div style="display:flex;gap:5px;">
           <div style="flex:1"><label>Password</label><input type="password" id="b-pass-${i}" value="${b.password}"></div>
           <div style="flex:1"><label>MT5 Path (Optional)</label><input type="text" id="b-path-${i}" value="${b.path}"></div>
        </div>
      </div>
    `;
  });
  document.getElementById('settings-modal').style.display = 'flex';
}

function closeSettings() {
  document.getElementById('settings-modal').style.display = 'none';
}

function collectBrokerInputs() {
  for (let i = 0; i < brokersData.brokers.length; i++) {
    brokersData.brokers[i].name = document.getElementById(`b-name-${i}`).value;
    brokersData.brokers[i].server = document.getElementById(`b-srv-${i}`).value;
    brokersData.brokers[i].login = parseInt(document.getElementById(`b-log-${i}`).value, 10) || 0;
    brokersData.brokers[i].password = document.getElementById(`b-pass-${i}`).value;
    brokersData.brokers[i].path = document.getElementById(`b-path-${i}`).value;
  }
}

async function activateBroker(index) {
  collectBrokerInputs();
  brokersData.active_broker = index;
  await saveSettings();
  openSettings(); // redrarw modal
}

async function saveSettings() {
  collectBrokerInputs();
  document.getElementById('settings-modal').style.display = 'none';
  await pywebview.api.save_brokers(JSON.stringify(brokersData));
  document.getElementById('status').textContent = "↻ Reconnecting...";
  setTimeout(() => refreshData(), 500);
}

resize();
window.addEventListener('pywebviewready', () => {
  loadData('4h').then(() => startAutoRefresh());
});
</script>
</body>
</html>"""

def open_footprint_window(interval="4h"):
    import webview
    import threading
    import time
    import os
    from sync_zones_to_mt4 import install_all
    
    # ── Запускаем авто-патчер терминалов в фоне ──
    def run_patcher():
        print("[patcher] Scanning for MT4/MT5 terminals to apply Indicators...")
        install_all()
    threading.Thread(target=run_patcher, daemon=True).start()

    collector = get_collector()
    if all(v == 0 for v in collector.get_stats().values()):
        collector.load_all()
    collector.start_background_updates(60)

    api = API(collector)
    
    window = webview.create_window(
        "Smart Zones Pro — Footprint",
        html=HTML, js_api=api,
        width=1500, height=920, resizable=True,
        background_color="#131722",
    )
    
    # Обработчик закрытия (прячем в трей вместо уничтожения)
    def on_closing():
        window.hide()
        print("[tray] Window hidden to tray.")
        return False
        
    window.events.closing += on_closing
    
    # ── System Tray (иконка) ──
    def tray_thread():
        try:
            import pystray
            from PIL import Image, ImageDraw
            
            image = Image.new('RGB', (64, 64), color=(19, 23, 34))
            dc = ImageDraw.Draw(image)
            dc.ellipse([8, 8, 56, 56], fill=(41, 98, 255))
            
            def on_show(icon, item):
                window.show()
                
            def on_exit(icon, item):
                print("[tray] Exiting application...")
                icon.stop()
                window.events.closing -= on_closing
                window.destroy()
                os._exit(0)
                
            icon = pystray.Icon("Smart Zones Pro", image, "Smart Zones Footprint\nRunning in background", menu=pystray.Menu(
                pystray.MenuItem("Show Footprint", on_show, default=True),
                pystray.MenuItem("Exit", on_exit)
            ))
            icon.run()
        except ImportError:
            print("[tray] 'pystray' or 'Pillow' not installed. Tray icon disabled.")
            
    threading.Thread(target=tray_thread, daemon=True).start()
    
    # ── Мониторинг запросов от MT4 (открытие при клике на FP) ──
    def monitor_mt4_requests():
        common_base = Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal" / "Common" / "Files"
        flag = common_base / "footprint_request.flag"
        while True:
            if flag.exists():
                try:
                    tf = flag.read_text().strip() or "4h"
                    flag.unlink()
                    window.show()
                    window.evaluate_js(f"if(typeof switchTF === 'function') switchTF('{tf}');")
                    print(f"[bridge] MT4 called Footprint for {tf}")
                except Exception as e:
                    print(f"[bridge] Monitor error: {e}")
            time.sleep(1)
            
    threading.Thread(target=monitor_mt4_requests, daemon=True).start()

    # Блокирует главный поток
    webview.start()

if __name__ == "__main__":
    print("[footprint] Starting...")
    collector = get_collector()
    collector.load_all()
    open_footprint_window("4h")
