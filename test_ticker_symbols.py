import requests
import json
import sqlite3

conn = sqlite3.connect('data/stock_data.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

symbols = ["DOGEUSDT", "PEPEUSDT", "AVAXUSDT", "ZKUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT"]
c.execute("SELECT DISTINCT symbol FROM crypto_pump_positions WHERE status IN ('OPEN', 'TP1_HIT')")
for r in c.fetchall():
    if r["symbol"] not in symbols:
        symbols.append(r["symbol"])

print("Symbols list:", symbols)
s_json = json.dumps(symbols, separators=(',', ':'))
for ep in ["https://data-api.binance.vision", "https://api.binance.com"]:
    url = f"{ep}/api/v3/ticker/price?symbols={s_json}"
    r = requests.get(url, timeout=3)
    print(f"Endpoint {ep}: status={r.status_code}")
    if r.status_code == 200:
        print("Success! First 3:", r.json()[:3])
    else:
        print("Error response:", r.text)
