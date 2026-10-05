import sys
sys.path.insert(0, ".")
from data.fetcher import DataFetcher
from indicators.technical import TechnicalIndicators
import pandas as pd

f = DataFetcher()
df_m15 = f.fetch_and_store("GC=F", interval="15m", period="2d")
df_m15 = TechnicalIndicators.add_all_indicators(df_m15)
for idx, row in df_m15.tail(15).iterrows():
    o = row['Open']
    h = row['High']
    l = row['Low']
    c = row['Close']
    rsi = row.get('rsi', 0)
    ema20 = row.get('ema_20', 0)
    ema50 = row.get('ema_50', 0)
    print(f"{idx} | O:{o:.2f} H:{h:.2f} L:{l:.2f} C:{c:.2f} | RSI:{rsi:.1f} | EMA20:{ema20:.2f} | EMA50:{ema50:.2f}")
