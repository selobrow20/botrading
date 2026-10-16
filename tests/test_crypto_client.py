"""
Unit test untuk modul CryptoExchangeClient dan integrasi normalisasi Crypto.
"""

import pytest
from crypto.exchange_client import CryptoExchangeClient
from data.fetcher import DataFetcher


def test_crypto_normalize_symbol():
    assert CryptoExchangeClient.normalize_symbol("btc") == "BTCUSDT"
    assert CryptoExchangeClient.normalize_symbol("ethusdt") == "ETHUSDT"
    assert CryptoExchangeClient.normalize_symbol("sol-usd") == "SOLUSDT"


def test_data_fetcher_normalize_crypto():
    assert DataFetcher.normalize_ticker("BTC") == "BTC-USD"
    assert DataFetcher.normalize_ticker("BTCUSD") == "BTC-USD"
    assert DataFetcher.normalize_ticker("ETH") == "ETH-USD"
    assert DataFetcher.normalize_ticker("SOLUSDT") == "SOL-USD"


def test_crypto_client_unauthenticated_balance():
    client = CryptoExchangeClient(api_key="", secret_key="")
    assert client.is_authenticated() is False
    bal = client.get_balance()
    assert bal["authenticated"] is False
    assert "belum dikonfigurasi" in bal["message"]


def test_crypto_client_create_order_unauthenticated():
    client = CryptoExchangeClient(api_key="", secret_key="")
    res = client.create_order("BTC/USDT", "buy", "limit", 0.001, 80000.0)
    assert res["success"] is False
    assert "API Key belum terpasang" in res["error"]
