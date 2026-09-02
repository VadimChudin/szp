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
    data = paths.load_json_file(ZONES_FILE, default={})
    return data.get("zones", [])

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
        except (json.JSONDecodeError, OSError) as e:
            print(f"[footprint] WARN: Could not load brokers config: {e}")
        return json.dumps({"active_broker": 0, "brokers": []})

    def save_brokers(self, config_str):
        try:
            data = json.loads(config_str)
            BROKERS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(BROKERS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            return True
        except json.JSONDecodeError as e:
            print(f"[footprint] ERROR: Invalid brokers JSON: {e}")
            return False
        except OSError as e:
            print(f"[footprint] ERROR: Could not save brokers config: {e}")
            return False

HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Smart Zones Pro — Footprint</title>
<style>
/* ── Liquid Glass theme ──────────────────────────────────────────── */
:root{
  --accent:#0a84ff; --accent-dk:#409cff;
  --accent-soft:rgba(10,132,255,0.14); --accent-glow:rgba(10,132,255,0.30);
  --aqua:#64d2ff; --gold:#ffd60a;
  --panel:#1c1c1e; --panel-hi:#2c2c2e; --card:#242426;
  --glass:rgba(255,255,255,0.045); --glass-strong:rgba(255,255,255,0.09);
  --stroke:rgba(255,255,255,0.12); --stroke-soft:rgba(255,255,255,0.06);
  --txt:#f5f5f7; --txt-dim:#aeaeb2; --txt-mute:#8e8e93;
  --ok:#30d158; --bad:#ff453a;
}
* { margin:0; padding:0; box-sizing:border-box; user-select:none;
    -webkit-font-smoothing:antialiased; }
button, input { font:inherit; }
button:focus-visible, input:focus-visible { outline:2px solid var(--aqua); outline-offset:2px; }
body {
  overflow:hidden; color:var(--txt);
  font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display','SF Pro Text','Inter','Segoe UI',Roboto,sans-serif;
  background:
    radial-gradient(1000px 600px at 6% -10%, rgba(10,132,255,0.10), transparent 60%),
    radial-gradient(820px 520px at 98% 0%, rgba(100,210,255,0.06), transparent 60%),
    #000000;
}
#toolbar {
  height:54px; display:flex; align-items:center; gap:8px;
  padding:0 16px; font-size:13px; position:relative; z-index:5;
  background:rgba(28,28,30,0.72); backdrop-filter:saturate(180%) blur(20px); -webkit-backdrop-filter:saturate(180%) blur(20px);
  backdrop-filter:blur(24px) saturate(150%);
  -webkit-backdrop-filter:blur(24px) saturate(150%);
  border-bottom:1px solid var(--stroke);
  box-shadow:0 10px 32px rgba(0,0,0,0.34), inset 0 1px 0 rgba(255,255,255,0.045);
}
#toolbar .logo {
  font-weight:700; letter-spacing:0.5px; font-size:14px; color:var(--txt);
  display:flex; align-items:center; gap:8px;
}
#toolbar .logo::before {
  content:''; width:9px; height:9px; border-radius:3px;
  background:var(--accent); box-shadow:0 0 10px var(--accent-glow);
}
#toolbar .sep { width:1px; height:22px; background:var(--stroke); margin:0 6px; opacity:0.7; }
.tf-btn {
  padding:8px 16px; border:1px solid var(--stroke-soft); border-radius:12px; cursor:pointer;
  font-size:12px; font-weight:600; background:linear-gradient(145deg,rgba(255,255,255,0.075),rgba(255,255,255,0.025)); color:var(--txt-dim);
  transition:all 0.18s ease; box-shadow:inset 0 1px 0 rgba(255,255,255,0.04);
}
.tf-btn:hover { color:var(--txt); border-color:var(--stroke); background:linear-gradient(145deg,rgba(255,255,255,0.12),rgba(255,255,255,0.04)); transform:translateY(-1px); }
.tf-btn.active {
  color:var(--txt); border-color:rgba(184,243,90,0.48);
  background:linear-gradient(145deg,rgba(184,243,90,0.16),rgba(119,228,208,0.06));
  box-shadow:inset 0 -2px 0 var(--accent), 0 0 22px var(--accent-glow);
}
.nav-btn {
  padding:7px 12px; border:1px solid var(--stroke-soft); border-radius:11px; cursor:pointer;
  font-size:14px; background:linear-gradient(145deg,rgba(255,255,255,0.075),rgba(255,255,255,0.025)); color:var(--txt-dim); transition:all 0.18s ease;
  box-shadow:inset 0 1px 0 rgba(255,255,255,0.04);
}
.nav-btn:hover { color:var(--txt); background:linear-gradient(145deg,rgba(255,255,255,0.12),rgba(255,255,255,0.04)); border-color:var(--stroke); transform:translateY(-1px); }
#info { margin-left:auto; font-size:12px; color:var(--txt-dim); font-family:'JetBrains Mono','Courier New',monospace; font-weight:600; }
#status { font-size:11px; color:var(--ok); margin-left:10px; }
canvas { display:block; cursor:crosshair; }
#auto-btn {
  position:absolute; bottom:80px; right:14px; color:var(--txt);
  background:var(--panel-hi); border:1px solid var(--stroke); border-radius:12px;
  padding:7px 13px; font-size:11px; cursor:pointer; backdrop-filter:blur(14px);
  box-shadow:0 6px 18px rgba(0,0,0,0.40); transition:0.15s; display:none;
}
#auto-btn:hover { border-color:rgba(166,226,46,0.4); box-shadow:0 0 16px var(--accent-glow); }
/* Modal Styles — matte glass card */
.modal-overlay {
  position:fixed; top:0; left:0; width:100%; height:100%;
  background:rgba(5,5,6,0.62); backdrop-filter:blur(6px);
  display:none; align-items:center; justify-content:center; z-index:999;
}
.modal {
  width:470px; padding:26px; border-radius:22px;
  background:linear-gradient(165deg,rgba(27,48,64,0.92),rgba(10,21,32,0.94));
  backdrop-filter:blur(26px) saturate(140%);
  -webkit-backdrop-filter:blur(26px) saturate(140%);
  border:1px solid var(--stroke);
  box-shadow:0 28px 70px rgba(0,0,0,0.62), inset 0 1px 0 rgba(255,255,255,0.05);
}
.modal h2 { color:var(--txt); font-size:16px; font-weight:700; margin-bottom:16px; border-bottom:1px solid var(--stroke-soft); padding-bottom:12px; }
.broker-slot { margin-bottom:14px; padding:14px; border:1px solid var(--stroke-soft); border-radius:16px; background:var(--card); position:relative; }
.broker-slot.active { border-color:rgba(184,243,90,0.50); background:linear-gradient(145deg,rgba(184,243,90,0.10),rgba(119,228,208,0.035)); box-shadow:inset 3px 0 0 var(--accent), 0 0 22px var(--accent-glow); }
.broker-slot input {
  display:block; width:100%; padding:9px 11px; margin-bottom:6px;
  background:rgba(5,15,25,0.66); border:1px solid var(--stroke-soft); color:var(--txt);
  border-radius:11px; font-size:12px; transition:border-color 0.15s;
}
.broker-slot input:focus { outline:none; border-color:var(--aqua); box-shadow:0 0 0 3px rgba(119,228,208,0.10); }
.broker-slot label { font-size:10px; color:var(--txt-mute); display:block; margin-bottom:3px; letter-spacing:0.5px; text-transform:uppercase; }
.btn-row { display:flex; justify-content:space-between; margin-top:22px; gap:10px; }
.btn-save {   background:linear-gradient(135deg,var(--accent),#d5ff87); color:#0a1309; border:none; padding:11px 20px; border-radius:13px; cursor:pointer; font-weight:700; box-shadow:0 8px 24px var(--accent-glow); transition:0.15s;
 }
.btn-save:hover { background:var(--accent-dk); }
.btn-close {   background:linear-gradient(145deg,rgba(255,255,255,0.09),rgba(255,255,255,0.035)); color:var(--txt-dim); border:1px solid var(--stroke-soft); padding:11px 20px; border-radius:13px; cursor:pointer; transition:0.15s;
 }
.btn-close:hover { background:linear-gradient(145deg,rgba(255,255,255,0.13),rgba(255,255,255,0.05)); color:var(--txt); }
.btn-activate { position:absolute; top:12px; right:12px; background:var(--accent); color:#0b0e08; border:none; padding:6px 11px; border-radius:10px; font-size:10px; font-weight:700; cursor:pointer; }
.btn-activate:hover { background:var(--accent-dk); }
</style>
</head>
<body>
<div id="toolbar">
  <span class="logo">SMART ZONES · FOOTPRINT</span>
  <span class="sep"></span>
  <button class="tf-btn" data-tf="1h" onclick="switchTF('1h')">1H</button>
  <button class="tf-btn active" data-tf="4h" onclick="switchTF('4h')">4H</button>
  <button class="tf-btn" data-tf="1d" onclick="switchTF('1d')">1D</button>
  <span class="sep"></span>
  <button id="zk-btn" class="tf-btn active" onclick="toggleZakrep()" title="Показать/скрыть метку ЗАКРЕП">ZAKREP</button>
  <span class="sep"></span>
  <button class="nav-btn" onclick="sc(-10)" title="Home">⏮</button>
  <button class="nav-btn" onclick="sc(-3)">◀</button>
  <button class="nav-btn" onclick="sc(3)">▶</button>
  <button class="nav-btn" onclick="sc(10)" title="End">⏭</button>
  <span class="sep"></span>
  <button class="nav-btn" onclick="zm(-2)" title="Zoom In">🔍+</button>
  <button class="nav-btn" onclick="zm(2)" title="Zoom Out">🔍−</button>
  <span class="sep"></span>
  <button class="nav-btn" onclick="refreshData()" title="Refresh" style="color:#b8f35a">⟳</button>
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
let showZakrep = true;
function toggleZakrep() {
  showZakrep = !showZakrep;
  const b = document.getElementById('zk-btn');
  if (b) b.classList.toggle('active', showZakrep);
  if (DATA) draw();
}
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
    document.getElementById('status').style.color = '#f3c969';
    document.getElementById('status').textContent = '◌';
    const raw = await pywebview.api.get_data(tf || currentTF);
    DATA = JSON.parse(raw);
    currentTF = DATA.tf || currentTF;
    scrollPos = Math.max(0, DATA.candles.length - visibleCount);
    autoScaleY = true;
    draw();
    document.getElementById('status').style.color = '#b8f35a';
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
    document.getElementById('status').style.color = '#b8f35a';
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

  const bgCol = '#08111b';
  const gridCol = 'rgba(170,205,222,0.10)';
  const textCol = '#9aabb9';

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
    // Actionable line: the center price is the display level. The width is
    // retained in JSON for SL/risk calculations but no longer obscures data.
    const zPrice = (z.price !== undefined && z.price !== null)
                   ? Number(z.price)
                   : ((Number(z.top || 0) + Number(z.bottom || 0)) / 2);
    const zy = py(zPrice);

    const score = z.score || 0;

    // Клиент: ВСЕ зоны красные (Apple systemRed). Никакой цветовой иерархии.
    let bgFill   = 'rgba(255,59,48,0.10)';
    let edgeCol  = 'rgba(255,59,48,0.85)';
    let textCol2 = '#ff6961';

    // Одна тонкая линия вместо прямоугольного диапазона.
    ctx.strokeStyle = edgeCol;
    ctx.lineWidth = z.is_fallback ? 1.1 : (score >= 13 ? 2.4 : score >= 11 ? 1.8 : 1.15);
    ctx.setLineDash(z.is_fallback || score < 11 ? [5, 4] : []);
    ctx.beginPath(); ctx.moveTo(ml, zy); ctx.lineTo(chartW, zy); ctx.stroke();
    ctx.setLineDash([]);
    // Subtle glow keeps strong levels readable without filling the chart.
    ctx.save();
    ctx.globalAlpha = 0.18;
    ctx.lineWidth += 3;
    ctx.beginPath(); ctx.moveTo(ml, zy); ctx.lineTo(chartW, zy); ctx.stroke();
    ctx.restore();

    // Подпись зоны — ТОЛЬКО цена (без источников/скора), в стеклянной «пилюле».
    const label = zPrice.toFixed(2) + (z.is_fallback ? ' · F' : '');
    ctx.font = 'bold 11px "JetBrains Mono", "Courier New", monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    const padX = 8;
    const txtW = ctx.measureText(label).width;
    const badgeH = 18;
    const badgeW = txtW + padX * 2;
    const badgeX = chartW - 8 - badgeW;
    const badgeY = zy - badgeH / 2;
    const r = 6;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(badgeX, badgeY, badgeW, badgeH, r);
    else ctx.rect(badgeX, badgeY, badgeW, badgeH);
    ctx.fillStyle = 'rgba(8,17,27,0.82)';
    ctx.fill();
    ctx.strokeStyle = edgeCol;
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.fillStyle = textCol2;
    ctx.fillText(label, badgeX + badgeW - padX, badgeY + badgeH / 2);

    // Метка «ЗАКРЕП» — цена закрылась и удержалась за зоной (reaction на H1).
    if (showZakrep && z.reaction && z.reaction.type === 'BREAKOUT') {
      const zkArrow = z.reaction.direction === 'UP' ? '\u2191'
                    : z.reaction.direction === 'DOWN' ? '\u2193' : '';
      ctx.font = 'bold 11px "JetBrains Mono","Courier New",monospace';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = '#ffd60a';
      ctx.fillText('ZAKREP ' + zkArrow, ml + 10, zy - 9);
    }

    // Possible SL is shown as a separate structural liquidity line.
    if (z.sl && z.sl.price !== undefined) {
      const slPrice = Number(z.sl.price);
      const slY = py(slPrice);
      const slCol = '#bda7ff'; // SL is violet; red is reserved for fallback zones.
      ctx.save();
      ctx.strokeStyle = slCol;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 5]);
      ctx.globalAlpha = 0.78;
      ctx.beginPath(); ctx.moveTo(ml, slY); ctx.lineTo(chartW, slY); ctx.stroke();
      ctx.restore();
      const slLabel = 'SL ' + slPrice.toFixed(2) + ' · ' + (z.sl.probability || 0) + '%';
      ctx.font = '10px "JetBrains Mono", "Courier New", monospace';
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = slCol;
      ctx.fillText(slLabel, chartW - 10, slY - 7);
    }
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
        ctx.fillStyle = 'rgba(243,201,105,0.46)'; // champagne POC
        ctx.fillRect(xBuyL, yTop, halfW * 2, h);
      }

      // Рамки
      ctx.strokeStyle = 'rgba(158,195,214,0.16)';
      ctx.lineWidth = 0.5;
      ctx.strokeRect(xBuyL, yTop, halfW, h);
      ctx.strokeRect(xMid, yTop, halfW, h);

      // Buy fill (089981) - Линейно пропорционально ширине ячейки
      if (buy > 0) {
        // Минимальная видимая толщина 2 пикселя
        const fw = Math.max(2, halfW * (buy / candleMaxSide)); 
        ctx.fillStyle = 'rgba(72,205,174,0.72)'; // emerald buy
        ctx.fillRect(xBuyL, yTop, fw, h);
      }

      // Sell fill (f23645) - Линейно пропорционально ширине ячейки
      if (sell > 0) {
        const fw = Math.max(2, halfW * (sell / candleMaxSide));
        ctx.fillStyle = 'rgba(224,103,120,0.72)'; // ruby sell
        ctx.fillRect(xSellR - fw, yTop, fw, h);
      }

      // 🟡 Макс объём
      if (Math.abs(p - maxPr) < step*0.1 && maxT > mx * 0.1) {
        ctx.strokeStyle = '#f3c969'; ctx.lineWidth = 2;
        ctx.strokeRect(xBuyL, yTop, halfW * 2, h);
      }
      
      // 🔵 Мин объём
      if (Math.abs(p - minPr) < step*0.1 && minPr !== maxPr && lvlsCount > 2) {
        ctx.strokeStyle = '#77b8d6'; ctx.lineWidth = 1.5;
        ctx.strokeRect(xBuyL, yTop, halfW * 2, h);
      }

      // Текст только если высота ячейки достаточна
      const fs = Math.max(0, Math.min(12, h * 0.6));
      if (fs >= 6) {
        const ty = yTop + h/2;
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        if (buy > 0) {
          ctx.font = `${buy > candleMaxSide * 0.5 ? 'bold ' : ''}${fs}px Courier New`;
          ctx.fillStyle = buy > candleMaxSide * 0.5 ? '#f1fff9' : '#9fc4c5';
          const txt = buy >= 10 ? Math.round(buy).toString() : buy.toFixed(1);
          ctx.fillText(txt, xBuyL + halfW/2, ty);
        }
        if (sell > 0) {
          ctx.font = `${sell > candleMaxSide * 0.5 ? 'bold ' : ''}${fs}px Courier New`;
          ctx.fillStyle = sell > candleMaxSide * 0.5 ? '#fff5f5' : '#c9aeb4';
          const txt = sell >= 10 ? Math.round(sell).toString() : sell.toFixed(1);
          ctx.fillText(txt, xMid + halfW/2, ty);
        }
      }
    }

    // Тело свечи сбоку (TradingView colors)
    const bullCol = '#55d6b0'; const bearCol = '#e87988';
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
      ctx.fillStyle = '#b8f35a';
      ctx.beginPath();
      ctx.arc(xMid, py(candle.h) - 6, 3, 0, Math.PI * 2);
      ctx.fill();
    }

    // POC line (Point of Control) — оранжевая пунктирная линия
    if (candle.poc && candle.poc >= candle.l && candle.poc <= candle.h) {
      const pocY = py(candle.poc);
            ctx.strokeStyle = '#f3c969'; ctx.lineWidth = 2;

      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(xBuyL, pocY);
      ctx.lineTo(xSellR, pocY);
      ctx.stroke();
      ctx.setLineDash([]);

      // Подпись POC справа
      ctx.font = '9px Courier New';
      ctx.fillStyle = '#f3c969';
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
  ctx.strokeStyle = 'rgba(119,228,208,0.24)'; ctx.lineWidth = 0.5;
  ctx.beginPath(); ctx.moveTo(ml, dMid); ctx.lineTo(chartW, dMid); ctx.stroke();

  vis.forEach((c, j) => {
    const x = ml + j * colW + colW * 0.12;
    const bw = colW * 0.76;
    const bh = (Math.abs(c.d) / maxD) * (deltaH / 2 - 6);
    ctx.fillStyle = c.d >= 0 ? '#55d6b0' : '#e87988';
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
  ctx.strokeStyle = 'rgba(167,207,231,0.16)'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(chartW, 0); ctx.lineTo(chartW, chartH); ctx.stroke();

  gp = Math.ceil(minP / priceGridStep) * priceGridStep;
  ctx.font = '11px Courier New'; ctx.fillStyle = textCol; ctx.textAlign = 'right'; ctx.textBaseline='middle';
  while (gp <= maxP) {
    ctx.fillText(gp.toFixed(2), W - 6, py(gp));
    gp += priceGridStep;
  }

  // === Crosshair ===
  if (mouseX > ml && mouseX < chartW && mouseY > 0 && mouseY < chartH) {
    ctx.strokeStyle = 'rgba(119,228,208,0.42)';
    ctx.lineWidth = 0.5; ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(mouseX, 0); ctx.lineTo(mouseX, chartH); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(ml, mouseY); ctx.lineTo(chartW, mouseY); ctx.stroke();
    ctx.setLineDash([]);

    const crossPrice = minP + (1 - mouseY / chartH) * (maxP - minP);
    ctx.fillStyle = '#b8f35a';
    ctx.fillRect(chartW + 2, mouseY - 10, priceAxisW - 2, 20);
    ctx.fillStyle = '#0a1309'; ctx.font = 'bold 11px Courier New';
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
        ${!isActive ? `<button class="btn-activate" onclick="activateBroker(${i})">SET ACTIVE</button>` : `<span style="position:absolute;top:10px;right:10px;color:#78e8ca;font-size:11px;font-weight:bold;">● ACTIVE</span>`}
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
        background_color="#08111b",
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
