"""
BOTRADING 3D ISOMETRIC OFFICE DASHBOARD SERVER
Menyediakan REST API & Web Server lokal untuk dashboard HTML/CSS/JS.
Terhubung langsung ke MetaTrader 5 (MT5) lokal & sinkron dengan client copier.
"""

import os
import sys
import json
import time
import socket
import threading
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from datetime import datetime

# Windows Console UTF-8
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
DASHBOARD_DIR = BASE_DIR / "dashboard"
MEMBER_COPIER_DIR = BASE_DIR / "member_copier"
STATE_FILE = MEMBER_COPIER_DIR / "copier_live_state.json"

# Inisialisasi status global
GLOBAL_STATE = {
    "vps_master": {
        "status": "ONLINE",
        "username": "selo_saham_bot",
        "provider": "Selo Brow (Strategy 9 Buku PDF)",
        "server": "Ubuntu VPS Cloud",
        "latency_ms": 28,
        "last_signal": {
            "action": "BUY",
            "symbol": "XAUUSD",
            "entry": 4175.77,
            "tp": 4180.50,
            "sl": 4170.50,
            "time": "00:20:37"
        }
    },
    "gold_price": 4175.80,
    "recent_logs": [],
    "last_update": time.time()
}

def get_mt5_data() -> dict:
    """Mengambil data live dari terminal MetaTrader 5 jika terpasang."""
    data = {
        "connected": False,
        "login": 0,
        "server": "Offline / MT5 Standby",
        "balance": 0.0,
        "equity": 0.0,
        "margin": 0.0,
        "free_margin": 0.0,
        "currency": "USD",
        "positions": []
    }
    try:
        import MetaTrader5 as mt5
        if mt5.initialize():
            acc = mt5.account_info()
            if acc:
                data["connected"] = True
                data["login"] = acc.login
                data["server"] = acc.server
                data["balance"] = float(acc.balance)
                data["equity"] = float(acc.equity)
                data["margin"] = float(acc.margin)
                data["free_margin"] = float(acc.margin_free)
                data["currency"] = acc.currency

            # Ambil posisi trading terbuka
            positions = mt5.positions_get()
            pos_list = []
            if positions:
                for p in positions:
                    pos_list.append({
                        "ticket": p.ticket,
                        "symbol": p.symbol,
                        "type": "BUY" if p.type == 0 else "SELL",
                        "lot": p.volume,
                        "openPrice": p.price_open,
                        "profit": float(p.profit)
                    })
            data["positions"] = pos_list

            # Ambil tick harga emas
            for sym in ["XAUUSDc", "XAUUSD", "GOLD"]:
                tick = mt5.symbol_info_tick(sym)
                if tick:
                    GLOBAL_STATE["gold_price"] = (tick.bid + tick.ask) / 2.0
                    break

            mt5.shutdown()
    except Exception as e:
        # Fallback jika MT5 sedang diakses thread lain
        pass

    return data


class DashboardRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD_DIR), **kwargs)

    def log_message(self, format, *args):
        # Redam log akses static agar console tetap rapi
        return

    def do_GET(self):
        if self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            mt5_info = get_mt5_data()
            
            # Cek status file live jika ada update dari client_copier.py
            if STATE_FILE.exists():
                try:
                    with open(STATE_FILE, "r", encoding="utf-8") as f:
                        file_state = json.load(f)
                        if "last_signal" in file_state:
                            GLOBAL_STATE["vps_master"]["last_signal"] = file_state["last_signal"]
                except Exception:
                    pass

            response_data = {
                "status": "ok",
                "account": mt5_info,
                "positions": mt5_info.get("positions", []),
                "master": GLOBAL_STATE["vps_master"],
                "gold_price": GLOBAL_STATE["gold_price"],
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self.wfile.write(json.dumps(response_data).encode("utf-8"))
            return

        elif self.path == "/api/logs":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(GLOBAL_STATE["recent_logs"]).encode("utf-8"))
            return

        # Handle file static
        super().do_GET()

    def do_POST(self):
        if self.path == "/api/signal":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                sig = json.loads(body)
                now_str = datetime.now().strftime("%H:%M:%S")
                sig["time"] = now_str
                GLOBAL_STATE["vps_master"]["last_signal"] = sig
                
                # Simpan ke file state agar terbaca copier
                with open(STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump({"last_signal": sig, "timestamp": time.time()}, f, indent=2)

                print(f"\n⚡ [BROADCAST TEST] Sinyal Terkirim ke Trading Floor: {sig.get('action')} {sig.get('symbol')} @ ${sig.get('entry')}")

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "signal": sig}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.end_headers()
            return

        elif self.path == "/api/event":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                event = json.loads(body)
                GLOBAL_STATE["recent_logs"].append(event)
                if len(GLOBAL_STATE["recent_logs"]) > 100:
                    GLOBAL_STATE["recent_logs"].pop(0)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
            except Exception:
                self.send_response(400)
                self.end_headers()
            return

        self.send_response(404)
        self.end_headers()


def find_free_port(start_port=8080) -> int:
    port = start_port
    while port < start_port + 20:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
            port += 1
    return start_port


def run_server():
    port = find_free_port(8080)
    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, DashboardRequestHandler)

    url = f"http://127.0.0.1:{port}"
    print("=" * 70)
    print("🏢 BOTRADING 3D ISOMETRIC OFFICE & COPIER DASHBOARD SERVER")
    print("=" * 70)
    print(f"✓ Dashboard Web URL : {url}")
    print(f"✓ Direktori Aset    : {DASHBOARD_DIR}")
    print(f"✓ Live MT5 Bridge   : Otomatis Terhubung ke Akun MT5 Windows")
    print(f"✓ Status Master     : VPS Provider (@selo_saham_bot)")
    print("=" * 70)
    print("Tekan Ctrl + C di console ini untuk menghentikan server.\n")

    # Buka browser otomatis
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] Dashboard server dihentikan.")
        httpd.server_close()


if __name__ == "__main__":
    run_server()
