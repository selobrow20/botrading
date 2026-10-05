import re
import sys
sys.path.insert(0, ".")
from member_copier.client_copier import parse_signal, load_config

# Test 1: Normal Signal
sig1 = """
🟢 <b>SINYAL ENTRY (MASUK / BUY): XAU/USD</b>
📍 <b>Harga Entry:</b> <code>$4,188.54</code>
🎯 <b>Take Profit (TP):</b> <code>$4,220.31</code> (+0.76%)
🛑 <b>Stop Loss (SL):</b> <code>$4,174.89</code> (-0.33%)
"""
res1 = parse_signal(sig1)
print("Res1:", res1)
assert res1["action"] == "BUY"
assert res1["entry_price"] == 4188.54
assert res1["tp_price"] == 4220.31
assert res1["sl_price"] == 4174.89

# Test 2: Reports should be ignored
rep1 = "📊 LAPORAN PENUTUPAN: BUY XAUUSD TP tercapai +$45.00"
assert parse_signal(rep1) == {}

rep2 = "🤖 DEAL #15246104767 BUY 0.05 lot @ 4188.54 sukses dieksekusi"
assert parse_signal(rep2) == {}

# Test 3: SELL Signal
sig2 = """
🔴 <b>SINYAL ENTRY SHORT (SELL): XAU/USD</b>
📍 <b>Harga Entry Short:</b> <code>$4,190.24</code>
🎯 <b>Take Profit (TP):</b> <code>$4,160.00</code>
🛑 <b>Stop Loss (SL):</b> <code>$4,210.00</code>
"""
res2 = parse_signal(sig2)
print("Res2:", res2)
assert res2["action"] == "SELL"
assert res2["entry_price"] == 4190.24
assert res2["tp_price"] == 4160.00
assert res2["sl_price"] == 4210.00

# Test 4: Mock MT5 Accounts for Cent vs Standard detection
class MockAccount:
    def __init__(self, currency="USD", server="Broker-Server", balance=500.0, company=""):
        self.login = 12345
        self.currency = currency
        self.server = server
        self.balance = balance
        self.company = company

class MockSymbolInfo:
    def __init__(self, name, trade_mode=4, visible=True, volume_min=0.01, volume_max=100.0, volume_step=0.01, digits=2):
        self.name = name
        self.trade_mode = trade_mode
        self.visible = visible
        self.volume_min = volume_min
        self.volume_max = volume_max
        self.volume_step = volume_step
        self.digits = digits

class MockMT5:
    def __init__(self, account, symbols):
        self._acc = account
        self._symbols = {s.name: s for s in symbols}
    def account_info(self):
        return self._acc
    def symbol_info(self, name):
        return self._symbols.get(name)
    def symbols_get(self):
        return list(self._symbols.values())
    def symbol_select(self, name, enable):
        return True

from member_copier.client_copier import MT5MemberBridge

# Case A: Cent Account HFMarkets (currency USC, symbol XAUUSDc)
b_cent = MT5MemberBridge(load_config())
b_cent.mt5 = MockMT5(
    account=MockAccount(currency="USC", server="HFMarketsGlobal-Live7", balance=10000.0),
    symbols=[MockSymbolInfo("XAUUSDc")]
)
assert b_cent.is_cent_account() == True, "HFMarkets should be Cent"
assert b_cent.find_broker_symbol() == "XAUUSDc", "Should pick XAUUSDc"

# Case B: Cent Account Exness / FBS (currency USD, server FBS-Cent, symbol XAUUSDc)
b_fbs = MT5MemberBridge(load_config())
b_fbs.mt5 = MockMT5(
    account=MockAccount(currency="USD", server="FBS-Cent", balance=5000.0),
    symbols=[MockSymbolInfo("XAUUSDc")]
)
assert b_fbs.is_cent_account() == True, "FBS-Cent should be Cent"
assert b_fbs.find_broker_symbol() == "XAUUSDc", "Should pick XAUUSDc"

# Case C: Standard Account IC Markets (currency USD, server ICMarketsSC-Live, symbol XAUUSD)
b_std = MT5MemberBridge(load_config())
b_std.mt5 = MockMT5(
    account=MockAccount(currency="USD", server="ICMarketsSC-Live01", balance=500.0),
    symbols=[MockSymbolInfo("XAUUSD")]
)
assert b_std.is_cent_account() == False, "IC Markets should be Standard USD"
assert b_std.find_broker_symbol() == "XAUUSD", "Should pick XAUUSD"

print("\n>>> ALL MOCK ACCOUNT CENT VS STANDARD TESTS PASSED! <<<")

