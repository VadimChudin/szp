import urllib.request
import struct
import lzma
import os
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone, timedelta
import concurrent.futures

# ── Дисковый кэш: скачанные .bi5 сохраняются как .parquet ──────────
CACHE_DIR = Path(__file__).parent / "duka_cache"
CACHE_DIR.mkdir(exist_ok=True)


class DukascopyLoader:
    def __init__(self, max_workers=10):
        self.max_workers = max_workers
        self.base_url = "https://datafeed.dukascopy.com/datafeed"

    def _cache_key(self, symbol, dt: datetime) -> Path:
        """Путь к кэш-файлу для (symbol, hour)."""
        return CACHE_DIR / f"{symbol}_{dt.strftime('%Y%m%d_%H')}.parquet"

    def fetch_hour(self, symbol, dt: datetime):
        """Скачивает тики за один час. Использует кэш если есть."""
        cache_path = self._cache_key(symbol, dt)
        
        # ── Кэш-hit: читаем с диска ─────────────────────────────────
        if cache_path.exists():
            try:
                return pd.read_parquet(cache_path)
            except Exception:
                cache_path.unlink(missing_ok=True)  # битый кэш — удаляем
        
        # ── Кэш-miss: качаем с сервера ──────────────────────────────
        year = dt.year
        month_str = f"{dt.month - 1:02d}"  # Dukascopy index (00-11)
        day_str = f"{dt.day:02d}"
        hour_str = f"{dt.hour:02d}"
        
        url = f"{self.base_url}/{symbol}/{year}/{month_str}/{day_str}/{hour_str}h_ticks.bi5"
        
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status != 200:
                    return None
                
                data = lzma.decompress(response.read())
                if not data:
                    return None
                
                point = 0.001 if "XAUUSD" in symbol else 0.00001
                base_time_ms = dt.timestamp() * 1000
                
                ticks = []
                for i in range(0, len(data), 20):
                    chunk = data[i:i+20]
                    if len(chunk) < 20: continue
                    t_delta, ask, bid, a_vol, b_vol = struct.unpack(">IIIff", chunk)
                    
                    ticks.append({
                        "time_ms": base_time_ms + t_delta,
                        "time": datetime.fromtimestamp((base_time_ms + t_delta) / 1000, tz=timezone.utc),
                        "ask": ask * point,
                        "bid": bid * point,
                        "ask_vol": a_vol,
                        "bid_vol": b_vol
                    })
                df = pd.DataFrame(ticks)
                
                # ── Пишем в кэш ─────────────────────────────────────
                if not df.empty:
                    df.to_parquet(cache_path, index=False)
                else:
                    # Кэшируем пустой файл, чтобы не скачивать битые часы заново
                    pd.DataFrame(columns=["time_ms", "time", "ask", "bid", "ask_vol", "bid_vol"]).to_parquet(cache_path, index=False)
                return df
        except Exception:
            try:
                import pandas as pd
                pd.DataFrame(columns=["time_ms", "time", "ask", "bid", "ask_vol", "bid_vol"]).to_parquet(cache_path, index=False)
            except:
                pass
            return None

    def fetch_history(self, symbol, days_back=7, progress_cb=None) -> pd.DataFrame:
        """Скачивает историю за последние N дней (с кэшем + параллельно)."""
        print(f"[dukascopy] Fetching {days_back} days of tick history for {symbol}...")
        
        now = datetime.now(timezone.utc)
        end_time = now.replace(minute=0, second=0, microsecond=0)
        start_time = end_time - timedelta(days=days_back)
        
        hours_to_fetch = []
        current = start_time
        while current < end_time:
            hours_to_fetch.append(current)
            current += timedelta(hours=1)
            
        total_hours = len(hours_to_fetch)
        
        # Считаем сколько уже в кэше
        cached = sum(1 for h in hours_to_fetch if self._cache_key(symbol, h).exists())
        to_dl = total_hours - cached
        print(f"[dukascopy] {total_hours} hours total, {cached} cached, {to_dl} to download")
        
        dfs = []
        done_count = 0
        
        def _fetch_one(h):
            return self.fetch_hour(symbol, h)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {pool.submit(_fetch_one, h): h for h in hours_to_fetch}
            for future in concurrent.futures.as_completed(futures):
                done_count += 1
                df = future.result()
                if df is not None and not df.empty:
                    dfs.append(df)
                if progress_cb:
                    pct = int(done_count / total_hours * 100)
                    progress_cb(pct)
                    
        if dfs:
            print(f"[dukascopy] Merging {len(dfs)} hourly files...")
            full_df = pd.concat(dfs, ignore_index=True)
            full_df.sort_values("time_ms", inplace=True)
            full_df.reset_index(drop=True, inplace=True)
            return full_df
        else:
            print("[dukascopy] Failed to fetch any historical data.")
            return pd.DataFrame()

if __name__ == "__main__":
    import time
    start = time.time()
    loader = DukascopyLoader(max_workers=5)
    df = loader.fetch_history("XAUUSD", days_back=3)
    print(f"Got {len(df)} ticks in {time.time()-start:.2f}s")
    if not df.empty:
        print(df.head())
        print(df.tail())
