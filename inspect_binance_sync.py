import sys
import json
import sqlite3
sys.stdout.reconfigure(encoding='utf-8')

print("=== 1. QUERYING REAL BINANCE SPOT ACCOUNT ===")
try:
    from crypto.exchange_client import CryptoExchangeClient
    client = CryptoExchangeClient()
    if not client.is_authenticated():
        print("[!] Client NOT authenticated with Binance!")
    else:
        bal = client.get_balance()
        print(f"Free USDT: {bal.get('free_usdt')}")
        print(f"Total USDT: {bal.get('total_usdt')}")
        print("\nAll Non-Zero Holdings in Binance Wallet:")
        for asset, data in sorted(bal.get('holdings', {}).items()):
            tot = float(data.get('total', 0))
            if tot > 0:
                print(f"  Asset: {asset:8} | Free: {data.get('free'):15} | Locked: {data.get('locked'):10} | Total: {tot}")
except Exception as e:
    print(f"Error querying Binance: {e}")

print("\n=== 2. QUERYING SQLITE DATABASE (crypto_pump_positions) ===")
try:
    conn = sqlite3.connect('data/stock_data.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    print("\nPositions WHERE status IN ('OPEN', 'TP1_HIT'):")
    c.execute("SELECT id, symbol, mode, status, quantity, entry_price, current_price, cost_usdt, sl_price, tp1_price, tp2_price, entry_time FROM crypto_pump_positions WHERE status IN ('OPEN', 'TP1_HIT') ORDER BY id DESC")
    open_pos = [dict(r) for r in c.fetchall()]
    for p in open_pos:
        print(f"  #{p['id']} {p['symbol']:10} status={p['status']:8} qty={p['quantity']} entry={p['entry_price']} cost={p['cost_usdt']} entry_time={p['entry_time']}")
    print(f"Total count in DB open: {len(open_pos)}")

    print("\nPositions WHERE status NOT IN ('OPEN', 'TP1_HIT') (Recent 10):")
    c.execute("SELECT id, symbol, mode, status, quantity, entry_price, close_price, cost_usdt, pnl_usdt, close_time, exit_reason FROM crypto_pump_positions WHERE status NOT IN ('OPEN', 'TP1_HIT') ORDER BY id DESC LIMIT 10")
    closed_pos = [dict(r) for r in c.fetchall()]
    for p in closed_pos:
        print(f"  #{p['id']} {p['symbol']:10} status={p['status']:12} qty={p['quantity']} close_p={p['close_price']} pnl={p['pnl_usdt']} reason={p['exit_reason']}")
except Exception as e:
    print(f"Error querying SQLite: {e}")
