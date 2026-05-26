"""
fvg_detector.py — Детектор имбалансов (Fair Value Gaps - FVG)

Алгоритм ищет структурные разрывы цены из 3-х свечей.
Бычий FVG: Минимальная цена 3-й свечи ВЫШЕ максимальной цены 1-й свечи.
Медвежий FVG: Максимальная цена 3-й свечи НИЖЕ минимальной цены 1-й свечи.

Скрипт возвращает список только *неперекрытых* (unmitigated) FVG.
"""

import pandas as pd

def detect_fvgs(df: pd.DataFrame) -> list[dict]:
    """
    Поиск всех неперекрытых FVG в DataFrame.
    """
    fvgs = []
    
    highs = df['high'].values
    lows = df['low'].values
    
    n = len(df)
    if n < 3:
        return []
        
    for i in range(2, n):
        # Индексы свечей:
        # i-2 = первая свеча (свеча до импульса)
        # i-1 = импульсная свеча (которая делает разрыв)
        # i   = третья свеча (которая формирует FVG)
        
        c1_high, c1_low = highs[i-2], lows[i-2]
        c3_high, c3_low = highs[i], lows[i]
        
        # Bullish FVG (Разрыв между хаем 1-й и лоем 3-й свечи)
        if c3_low > c1_high:
            fvg_top = c3_low
            fvg_bottom = c1_high
            fvgs.append({
                "type": "bullish",
                "top": fvg_top,
                "bottom": fvg_bottom,
                "created_at_idx": i,
                "mitigated": False
            })
            
        # Bearish FVG (Разрыв между лоем 1-й и хаем 3-й свечи)
        elif c3_high < c1_low:
            fvg_top = c1_low
            fvg_bottom = c3_high
            fvgs.append({
                "type": "bearish",
                "top": fvg_top,
                "bottom": fvg_bottom,
                "created_at_idx": i,
                "mitigated": False
            })
            
    # Теперь проверяем, какие из найденных FVG были перекрыты 
    # (митигированы) последующим движением цены.
    for fvg in fvgs:
        idx = fvg["created_at_idx"]
        
        for future_i in range(idx + 1, n):
            f_high, f_low = highs[future_i], lows[future_i]
            
            # Если цена зашла внутрь разрыва полностью (перекрытие gap)
            # В SMC часто считают митигированным, если цена закрыла половину или коснулась.
            # Мы будем использовать strict-митигацию: если будущая свеча коснулась противоположенной границы.
            if fvg["type"] == "bullish":
                if f_low <= fvg["bottom"]:
                    fvg["mitigated"] = True
                    break
            else: # bearish
                if f_high >= fvg["top"]:
                    fvg["mitigated"] = True
                    break

    # Оставляем только свежие неперекрытые FVG
    unmitigated = [f for f in fvgs if not f["mitigated"]]
    return unmitigated

if __name__ == "__main__":
    from data_fetcher import generate_sample_data
    data = generate_sample_data()
    # Тест на H4
    fvgs = detect_fvgs(data["H4"])
    print(f"Found {len(fvgs)} unmitigated FVGs on H4.")
    for f in fvgs[-5:]:
        print(f"  {f['type'].upper()} GAP: {f['bottom']:.2f} — {f['top']:.2f}")
