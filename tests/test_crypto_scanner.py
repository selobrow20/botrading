"""
Unit test untuk CryptoScanner: deteksi koin potensi pump dan koin meme/micin di Binance Spot.
"""

from unittest.mock import patch, MagicMock
from crypto.scanner import CryptoScanner


def test_crypto_scanner_category():
    assert "MEME" in CryptoScanner.get_category("PEPEUSDT")
    assert "MEME" in CryptoScanner.get_category("DOGEUSDT")
    assert "AI" in CryptoScanner.get_category("RENDERUSDT")
    assert "DEFI" in CryptoScanner.get_category("AEROUSDT")
    assert "ALTCOIN" in CryptoScanner.get_category("ETHFIUSDT")


def test_crypto_scanner_scoring_and_report():
    mock_tickers = [
        {
            "symbol": "PUMP1USDT",
            "lastPrice": "1.00",
            "highPrice": "1.02",
            "lowPrice": "0.90",
            "quoteVolume": "5000000.0",
            "priceChangePercent": "8.5",
        },
        {
            "symbol": "PEPEUSDT",
            "lastPrice": "0.00001",
            "highPrice": "0.0000105",
            "lowPrice": "0.000009",
            "quoteVolume": "12000000.0",
            "priceChangePercent": "6.0",
        },
    ]

    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_tickers
        mock_get.return_value = mock_resp

        candidates = CryptoScanner.scan_potential_pumps(min_volume_usd=100000.0, top_n=5)
        assert len(candidates) >= 1
        assert candidates[0]["score"] >= 80

        report = CryptoScanner.generate_pump_report(user_name="Budi", meme_only=False)
        assert "RADAR KOIN POTENSI PUMP" in report
        assert "Budi" in report
