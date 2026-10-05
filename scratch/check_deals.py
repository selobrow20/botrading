import sys
sys.path.insert(0, ".")
from trading.mt5_bridge import MT5Bridge
import pandas as pd

b = MT5Bridge()
ok, msg = b.connect()
print("MT5 Connected:", ok)
if ok:
    deals = b.get_closed_deals(hours=24)
    df = pd.DataFrame(deals)
    print(f"Total deals last 24h: {len(df)}")
    if not df.empty:
        today_deals = df[df["time_wib"].str.startswith("2026-10-02")]
        print(f"Total deals today (2026-10-02): {len(today_deals)}")
        pd.set_option("display.max_columns", 15)
        pd.set_option("display.width", 1000)
        pd.set_option("display.max_rows", 100)
        print(today_deals[["time_wib", "type", "volume", "entry_price", "price", "profit", "reason", "outcome", "comment"]])
        wins = today_deals[today_deals["profit"] > 0]
        losses = today_deals[today_deals["profit"] < 0]
        w_sum = wins["profit"].sum() if not wins.empty else 0.0
        l_sum = losses["profit"].sum() if not losses.empty else 0.0
        net = today_deals["profit"].sum() if not today_deals.empty else 0.0
        print("--- Ringkasan Hari Ini ---")
        print(f"Win: {len(wins)} | Lose: {len(losses)}")
        print(f"Total Profit: {w_sum:.2f} | Total Loss: {l_sum:.2f}")
        print(f"Net PnL Today: {net:.2f} USC")
