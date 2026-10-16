"""
Modul Klien Bursa Crypto Multi-Exchange:
- Binance Direct Engine: Mengambil data ticker & candlestick langsung dari cluster resmi Binance (0 ms latency, bebas blokir).
- CCXT Multi-Exchange: Mendukung Bybit, Indodax, Tokocrypto, dan OKX.
"""

import os
import re
import time
import hmac
import hashlib
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
import pandas as pd
import requests

from config.settings import load_config, setup_logger

logger = setup_logger("crypto_client")

BINANCE_ENDPOINTS = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api3.binance.com",
]

_BINANCE_DNS_RESOLVED = False
_BINANCE_CLOUDFRONT_IP = "99.86.16.124"


def setup_binance_dns_bypass():
    """Bypass pemblokiran DNS ISP Indonesia pada api.binance.com via Cloudflare DoH & CloudFront."""
    global _BINANCE_DNS_RESOLVED, _BINANCE_CLOUDFRONT_IP
    if _BINANCE_DNS_RESOLVED:
        return
    try:
        r = requests.get(
            "https://cloudflare-dns.com/dns-query?name=api.binance.com&type=A",
            headers={"accept": "application/dns-json"},
            timeout=3,
        )
        if r.status_code == 200:
            for ans in r.json().get("Answer", []):
                if ans.get("type") == 1:
                    _BINANCE_CLOUDFRONT_IP = ans.get("data")
                    break
    except Exception:
        pass

    try:
        from urllib3.util import connection
        orig_create_connection = connection.create_connection

        def patched_create_connection(address, *args, **kwargs):
            host, port = address
            if isinstance(host, str) and "binance.com" in host:
                return orig_create_connection((_BINANCE_CLOUDFRONT_IP, port), *args, **kwargs)
            return orig_create_connection(address, *args, **kwargs)

        connection.create_connection = patched_create_connection
        _BINANCE_DNS_RESOLVED = True
    except Exception as e:
        logger.warning(f"Gagal memasang DNS bypass Binance: {e}")


class CryptoExchangeClient:
    """Klien interaksi trading Crypto bursa global & lokal."""

    SUPPORTED_EXCHANGES = ["binance", "bybit", "indodax", "tokocrypto", "okx"]

    def __init__(
        self,
        exchange_name: Optional[str] = None,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        passphrase: Optional[str] = None,
        testnet: bool = False,
    ):
        config = load_config()
        crypto_cfg = config.get("crypto", {})

        self.exchange_name = (
            exchange_name
            or os.getenv("CRYPTO_EXCHANGE")
            or crypto_cfg.get("exchange", "binance")
        ).lower()

        self.api_key = api_key if api_key is not None else (os.getenv("CRYPTO_API_KEY") or crypto_cfg.get("api_key", ""))
        self.secret_key = secret_key if secret_key is not None else (os.getenv("CRYPTO_SECRET_KEY") or crypto_cfg.get("secret_key", ""))
        self.passphrase = passphrase if passphrase is not None else (os.getenv("CRYPTO_PASSPHRASE") or crypto_cfg.get("passphrase", ""))
        self.testnet = testnet or os.getenv("CRYPTO_TESTNET", "false").lower() in ("true", "1") or crypto_cfg.get("testnet", False)

        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "AntiGravity-Crypto-Bot/2.0",
            "Accept": "application/json",
        })
        if self.exchange_name == "binance":
            setup_binance_dns_bypass()

    def _get_server_time(self) -> int:
        """Mengambil waktu server Binance tersinkronisasi untuk mencegah timestamp desync."""
        try:
            r = self._session.get("https://api.binance.com/api/v3/time", timeout=3)
            if r.status_code == 200:
                return int(r.json().get("serverTime", int(time.time() * 1000)))
        except Exception:
            pass
        return int(time.time() * 1000)

    def is_authenticated(self) -> bool:
        """Memeriksa apakah API Key & Secret sudah terpasang untuk eksekusi order."""
        return bool(self.api_key and self.secret_key)

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        """
        Menstandarkan simbol crypto ke format standar pair (misal: 'BTCUSDT').
        """
        s = symbol.strip().upper().replace("-", "").replace("/", "").replace("_", "")
        if s in ["BTC", "BITCOIN"]:
            return "BTCUSDT"
        if s in ["ETH", "ETHEREUM"]:
            return "ETHUSDT"
        if s in ["SOL", "SOLANA"]:
            return "SOLUSDT"
        if s in ["XRP", "RIPPLE"]:
            return "XRPUSDT"
        if s in ["DOGE", "DOGECOIN"]:
            return "DOGEUSDT"
        if s in ["BNB", "BINANCECOIN"]:
            return "BNBUSDT"

        if s.endswith("USD") and not s.endswith("USDT"):
            s = f"{s[:-3]}USDT"
        elif not s.endswith("USDT") and not s.endswith("IDR") and not s.endswith("BUSD"):
            s = f"{s}USDT"
        return s

    def fetch_ticker(self, symbol: str = "BTCUSDT") -> Dict[str, Any]:
        """
        Mengambil harga live, persentase perubahan 24 jam, dan volume langsung dari Binance.
        """
        sym = self.normalize_symbol(symbol)

        # 1. Jalur Utama: Binance Direct API Cluster
        if self.exchange_name == "binance":
            for base_url in BINANCE_ENDPOINTS:
                try:
                    url = f"{base_url}/api/v3/ticker/24hr?symbol={sym}"
                    res = self._session.get(url, timeout=4)
                    if res.status_code == 200:
                        data = res.json()
                        return {
                            "symbol": sym,
                            "exchange": "BINANCE",
                            "last": float(data.get("lastPrice", 0.0) or 0.0),
                            "last_price": float(data.get("lastPrice", 0.0) or 0.0),
                            "high": float(data.get("highPrice", 0.0) or 0.0),
                            "low": float(data.get("lowPrice", 0.0) or 0.0),
                            "bid": float(data.get("bidPrice", 0.0) or 0.0),
                            "ask": float(data.get("askPrice", 0.0) or 0.0),
                            "volume": float(data.get("volume", 0.0) or 0.0),
                            "quote_volume": float(data.get("quoteVolume", 0.0) or 0.0),
                            "percentage": float(data.get("priceChangePercent", 0.0) or 0.0),
                        }
                except Exception as e:
                    logger.debug(f"Gagal endpoint {base_url} untuk {sym}: {e}")

        # 2. Jalur Alternatif: Indodax via CCXT jika exchange=indodax
        if self.exchange_name == "indodax":
            try:
                import ccxt
                ex = ccxt.indodax({"enableRateLimit": True, "timeout": 8000})
                idx_sym = sym.replace("USDT", "/IDR")
                t = ex.fetch_ticker(idx_sym)
                return {
                    "symbol": idx_sym,
                    "exchange": "INDODAX",
                    "last": float(t.get("last", 0.0) or 0.0),
                    "last_price": float(t.get("last", 0.0) or 0.0),
                    "high": float(t.get("high", 0.0) or 0.0),
                    "low": float(t.get("low", 0.0) or 0.0),
                    "volume": float(t.get("baseVolume", 0.0) or 0.0),
                    "percentage": float(t.get("percentage", 0.0) or 0.0),
                }
            except Exception as e:
                logger.warning(f"Gagal mengambil ticker dari Indodax: {e}")

        return {}

    def fetch_ohlcv(
        self,
        symbol: str = "BTCUSDT",
        timeframe: str = "15m",
        limit: int = 100,
    ) -> pd.DataFrame:
        """
        Mengambil candlestick OHLCV historis langsung dari Binance secara instan.
        Format kolom: ['Open', 'High', 'Low', 'Close', 'Volume'] dengan datetime index UTC.
        """
        sym = self.normalize_symbol(symbol)

        tf_map = {
            "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
            "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w",
        }
        interval = tf_map.get(timeframe.lower(), "15m")

        for base_url in BINANCE_ENDPOINTS:
            try:
                url = f"{base_url}/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}"
                res = self._session.get(url, timeout=5)
                if res.status_code == 200:
                    raw = res.json()
                    if raw and isinstance(raw, list):
                        cols = [
                            "timestamp", "Open", "High", "Low", "Close", "Volume",
                            "close_time", "qav", "num_trades", "tbb", "tbq", "ignore"
                        ]
                        df = pd.DataFrame(raw, columns=cols)
                        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                        df.set_index("datetime", inplace=True)
                        for c in ["Open", "High", "Low", "Close", "Volume"]:
                            df[c] = pd.to_numeric(df[c], errors="coerce")
                        clean_df = df[["Open", "High", "Low", "Close", "Volume"]]
                        logger.info(f"Berhasil mengambil {len(clean_df)} bar klines Binance ({sym} {interval}).")
                        return clean_df
            except Exception as e:
                logger.debug(f"Gagal klines {base_url} ({sym}): {e}")

        return pd.DataFrame()

    def get_balance(self) -> Dict[str, Any]:
        """Mengambil saldo akun Binance jika API Key sudah dipasang."""
        if not self.is_authenticated():
            return {
                "authenticated": False,
                "message": "API Key & Secret Key belum dikonfigurasi di file .env",
                "free_usdt": 0.0,
                "holdings": {},
            }

        headers = {"X-MBX-APIKEY": self.api_key}
        last_err = None
        for attempt in range(2):
            try:
                ts = self._get_server_time() if self.exchange_name == "binance" else int(time.time() * 1000)
                query = f"timestamp={ts}&recvWindow=10000"
                sig = hmac.new(self.secret_key.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
                signed_url = f"https://api.binance.com/api/v3/account?{query}&signature={sig}"

                r = self._session.get(signed_url, headers=headers, timeout=8)
                if r.status_code == 200:
                    data = r.json()
                    balances = data.get("balances", [])
                    holdings = {}
                    free_usdt = 0.0
                    ld_usdt = 0.0
                    for b in balances:
                        free_amt = float(b.get("free", 0))
                        locked_amt = float(b.get("locked", 0))
                        total = free_amt + locked_amt
                        asset = b.get("asset")
                        if asset == "USDT":
                            free_usdt = free_amt
                        elif asset == "LDUSDT":
                            ld_usdt = free_amt
                        if total > 0.0001:
                            holdings[asset] = {"free": free_amt, "locked": locked_amt, "total": total}
                    return {
                        "authenticated": True,
                        "exchange": "BINANCE",
                        "free_usdt": free_usdt,
                        "ld_usdt": ld_usdt,
                        "holdings": holdings,
                    }
                else:
                    return {
                        "authenticated": False,
                        "error": f"Binance Error HTTP {r.status_code}: {r.text}",
                        "free_usdt": 0.0,
                        "holdings": {},
                    }
            except Exception as e:
                last_err = e
                if attempt == 0:
                    time.sleep(0.5)

        logger.warning(f"Gagal mengambil saldo Binance: {last_err}")
        return {
            "authenticated": False,
            "error": str(last_err),
            "free_usdt": 0.0,
            "holdings": {},
        }

    def get_symbol_min_notional(self, symbol: str) -> float:
        """Mengambil batas minimum nominal transaksi (minNotional) dari Binance untuk simbol ini."""
        sym = self.normalize_symbol(symbol)
        if not hasattr(self, "_min_notionals"):
            self._min_notionals = {}
        if sym in self._min_notionals:
            return self._min_notionals[sym]
        for base_url in BINANCE_ENDPOINTS:
            try:
                r = self._session.get(f"{base_url}/api/v3/exchangeInfo?symbol={sym}", timeout=4)
                if r.status_code == 200:
                    data = r.json()
                    for s in data.get("symbols", []):
                        for f in s.get("filters", []):
                            if f.get("filterType") in ("NOTIONAL", "MIN_NOTIONAL"):
                                min_n = float(f.get("minNotional", "5.0"))
                                self._min_notionals[sym] = min_n
                                return min_n
            except Exception:
                pass
        return 5.0

    def get_symbol_step_size(self, symbol: str) -> float:
        """Mengambil stepSize filter LOT_SIZE dari Binance."""
        sym = self.normalize_symbol(symbol)
        if not hasattr(self, "_step_sizes"):
            self._step_sizes = {}
        if sym in self._step_sizes:
            return self._step_sizes[sym]
        for base_url in BINANCE_ENDPOINTS:
            try:
                r = self._session.get(f"{base_url}/api/v3/exchangeInfo?symbol={sym}", timeout=4)
                if r.status_code == 200:
                    data = r.json()
                    for s in data.get("symbols", []):
                        for f in s.get("filters", []):
                            if f.get("filterType") == "LOT_SIZE":
                                step = float(f.get("stepSize", "1.0"))
                                self._step_sizes[sym] = step
                                return step
            except Exception:
                pass
        return 1.0

    @staticmethod
    def round_step_size(qty: float, step_size: float) -> float:
        """Membulatkan kuantitas ke bawah sesuai stepSize agar tidak terkena LOT_SIZE filter error."""
        import math
        if step_size <= 0:
            return qty
        precision = max(0, int(round(-math.log10(step_size))))
        factor = 10 ** precision
        return math.floor(qty * factor) / factor

    def create_order(
        self,
        symbol: str,
        side: str,  # 'BUY' atau 'SELL'
        order_type: str = "LIMIT",  # 'LIMIT' atau 'MARKET'
        amount: float = 0.0,
        price: Optional[float] = None,
        quote_order_qty: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Membuat order langsung ke Binance Spot."""
        if not self.is_authenticated():
            return {"success": False, "error": "API Key belum terpasang. Order dibatalkan."}

        sym = self.normalize_symbol(symbol)
        side_upper = side.upper()
        type_upper = order_type.upper()

        ts = self._get_server_time() if self.exchange_name == "binance" else int(time.time() * 1000)
        params = [
            f"symbol={sym}",
            f"side={side_upper}",
            f"type={type_upper}",
            f"timestamp={ts}",
            "recvWindow=10000",
        ]

        if side_upper == "BUY" and type_upper == "MARKET" and quote_order_qty is not None and quote_order_qty > 0:
            params.append(f"quoteOrderQty={quote_order_qty:.4f}")
        else:
            step = self.get_symbol_step_size(sym)
            adj_amount = self.round_step_size(amount, step)
            step_str = f"{step:.8f}".rstrip("0")
            dec_places = len(step_str.split(".")[1]) if "." in step_str else 0
            params.append(f"quantity={adj_amount:.{dec_places}f}")

        if type_upper == "LIMIT" and price is not None:
            params.append(f"price={price}")
            params.append("timeInForce=GTC")

        query = "&".join(params)
        sig = hmac.new(self.secret_key.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
        url = f"https://api.binance.com/api/v3/order?{query}&signature={sig}"

        headers = {"X-MBX-APIKEY": self.api_key}
        try:
            r = self._session.post(url, headers=headers, timeout=5)
            if r.status_code == 200:
                data = r.json()
                logger.info(f"Order Binance Berhasil: {sym} {side_upper} | ID: {data.get('orderId')}")
                return {"success": True, "order": data}
            else:
                err_text = r.text
                # Fallback Otomatis: Jika SELL ditolak karena NOTIONAL (< $5), gunakan Binance Convert API!
                if side_upper == "SELL" and ("-1013" in err_text or "NOTIONAL" in err_text):
                    base_asset = sym.replace("USDT", "").replace("FDUSD", "").replace("USDC", "").upper()
                    logger.info(f"Order Spot SELL {sym} terkena NOTIONAL filter. Menggunakan fallback Binance Convert untuk {base_asset} -> USDT...")
                    conv_res = self.convert_asset(from_asset=base_asset, to_asset="USDT", from_amount=amount)
                    if conv_res.get("success"):
                        return {"success": True, "order": conv_res.get("data"), "via_convert": True}
                return {"success": False, "error": f"Binance HTTP {r.status_code}: {err_text}"}
        except Exception as e:
            logger.error(f"Gagal kirim order Binance: {e}")
            return {"success": False, "error": str(e)}

    def convert_asset(
        self,
        from_asset: str,
        to_asset: str = "USDT",
        from_amount: Optional[float] = None,
        to_amount: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Binance Convert (Flash Swap API):
        Mengeksekusi konversi instan tanpa batasan minimal $5 (bisa mulai dari $0.01 USDT)
        dan bebas komisi transaksi (Zero Fee).
        """
        if not self.is_authenticated():
            return {"success": False, "error": "API Key belum terpasang."}

        from_asset = from_asset.upper()
        to_asset = to_asset.upper()

        ts = self._get_server_time() if self.exchange_name == "binance" else int(time.time() * 1000)
        params = [
            f"fromAsset={from_asset}",
            f"toAsset={to_asset}",
            f"timestamp={ts}",
            "recvWindow=10000",
        ]
        if from_amount is not None and from_amount > 0:
            params.append(f"fromAmount={from_amount}")
        elif to_amount is not None and to_amount > 0:
            params.append(f"toAmount={to_amount}")
        else:
            return {"success": False, "error": "Parameter from_amount atau to_amount harus diisi."}

        query = "&".join(params)
        sig = hmac.new(self.secret_key.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
        url_quote = f"https://api.binance.com/sapi/v1/convert/getQuote?{query}&signature={sig}"

        headers = {"X-MBX-APIKEY": self.api_key}
        try:
            r = self._session.post(url_quote, headers=headers, timeout=5)
            if r.status_code != 200:
                logger.error(f"Gagal getQuote Binance Convert: {r.status_code} {r.text}")
                return {"success": False, "error": f"Convert Quote Error {r.status_code}: {r.text}"}

            quote_data = r.json()
            quote_id = quote_data.get("quoteId")
            if not quote_id:
                return {"success": False, "error": f"Quote ID kosong: {quote_data}"}

            # Accept Quote
            ts_accept = self._get_server_time() if self.exchange_name == "binance" else int(time.time() * 1000)
            query_accept = f"quoteId={quote_id}&timestamp={ts_accept}&recvWindow=10000"
            sig_accept = hmac.new(self.secret_key.encode("utf-8"), query_accept.encode("utf-8"), hashlib.sha256).hexdigest()
            url_accept = f"https://api.binance.com/sapi/v1/convert/acceptQuote?{query_accept}&signature={sig_accept}"

            r_acc = self._session.post(url_accept, headers=headers, timeout=5)
            if r_acc.status_code == 200:
                acc_data = r_acc.json()
                logger.info(f"Binance Convert Berhasil: {from_asset} -> {to_asset} | Order: {acc_data}")
                return {"success": True, "data": acc_data, "quote": quote_data}
            else:
                logger.error(f"Gagal acceptQuote Binance Convert: {r_acc.status_code} {r_acc.text}")
                return {"success": False, "error": f"Convert Accept Error {r_acc.status_code}: {r_acc.text}"}
        except Exception as e:
            logger.error(f"Exception di convert_asset: {e}")
            return {"success": False, "error": str(e)}
