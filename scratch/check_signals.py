import sqlite3
import pandas as pd

conn = sqlite3.connect("data/stock_data.db")
df = pd.read_sql_query("SELECT id, signal_type, price, take_profit_price, stop_loss_price, candle_time, outcome, outcome_note, reasons FROM signals WHERE ticker LIKE '%XAU%' ORDER BY id DESC LIMIT 15", conn)
for idx, row in df.iterrows():
    print(f"#{row['id']} {row['signal_type']} @ {row['price']} | TP: {row['take_profit_price']} | SL: {row['stop_loss_price']} | Time: {row['candle_time']} | Outcome: {row['outcome']}")
    clean_note = str(row['outcome_note']).encode('ascii', 'ignore').decode('ascii')
    print(f"  Note: {clean_note}")
    clean_reasons = str(row['reasons']).encode('ascii', 'ignore').decode('ascii')
    print(f"  Reasons: {clean_reasons[:150]}")
    print("-" * 60)
