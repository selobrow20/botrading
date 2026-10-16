import pytest
from datetime import datetime, time
from zoneinfo import ZoneInfo
from unittest.mock import patch, MagicMock
from trading.mt5_bridge import MT5Bridge


def test_is_us_session_window():
    """Menguji bahwa jendela Sesi US (19:00 - 04:00 WIB) terdeteksi secara akurat."""
    bridge = MT5Bridge(simulation_mode=True)
    tz = ZoneInfo("Asia/Jakarta")

    # Kasus 1: Pukul 19:30 WIB (Awal Sesi US) -> Harus True
    dt_us_early = datetime(2026, 10, 12, 19, 30, tzinfo=tz)
    with patch("trading.mt5_bridge.datetime") as mock_dt:
        mock_dt.now.return_value = dt_us_early
        assert bridge.is_us_session_window() is True

    # Kasus 2: Pukul 23:00 WIB (Pertengahan Sesi US) -> Harus True
    dt_us_mid = datetime(2026, 10, 12, 23, 0, tzinfo=tz)
    with patch("trading.mt5_bridge.datetime") as mock_dt:
        mock_dt.now.return_value = dt_us_mid
        assert bridge.is_us_session_window() is True

    # Kasus 3: Pukul 02:00 WIB (Dini hari Sesi US) -> Harus True
    dt_us_late = datetime(2026, 10, 13, 2, 0, tzinfo=tz)
    with patch("trading.mt5_bridge.datetime") as mock_dt:
        mock_dt.now.return_value = dt_us_late
        assert bridge.is_us_session_window() is True

    # Kasus 4: Pukul 10:00 WIB (Sesi Asia) -> Harus False
    dt_asia = datetime(2026, 10, 12, 10, 0, tzinfo=tz)
    with patch("trading.mt5_bridge.datetime") as mock_dt:
        mock_dt.now.return_value = dt_asia
        assert bridge.is_us_session_window() is False

    # Kasus 5: Pukul 15:00 WIB (Sesi London siang) -> Harus False
    dt_london = datetime(2026, 10, 12, 15, 0, tzinfo=tz)
    with patch("trading.mt5_bridge.datetime") as mock_dt:
        mock_dt.now.return_value = dt_london
        assert bridge.is_us_session_window() is False


def test_adaptive_gold_scan_rate():
    """Menguji logika interval adaptif: 2s saat Sesi US, 5s di luar Sesi US."""
    gold_scan_sec = 5
    gold_scan_us_sec = 2
    enable_adaptive = True

    _last_gold_scan_time = 0.0
    scan_count = 0

    def mock_pipeline_run():
        nonlocal scan_count
        scan_count += 1

    def evaluate_scan(current_ts, is_us):
        nonlocal _last_gold_scan_time
        target_interval = gold_scan_us_sec if (enable_adaptive and is_us) else gold_scan_sec
        if current_ts - _last_gold_scan_time < target_interval:
            return False
        _last_gold_scan_time = current_ts
        mock_pipeline_run()
        return True

    # 1. Di Sesi US (target: 2s)
    # T=100s -> Scan 1
    assert evaluate_scan(100.0, is_us=True) is True
    assert scan_count == 1

    # T=101s -> Skip (baru 1s, belum 2s)
    assert evaluate_scan(101.0, is_us=True) is False
    assert scan_count == 1

    # T=102s -> Scan 2 (genap 2s)
    assert evaluate_scan(102.0, is_us=True) is True
    assert scan_count == 2

    # T=103s -> Skip
    assert evaluate_scan(103.0, is_us=True) is False
    assert scan_count == 2

    # T=104s -> Scan 3 (genap 2s)
    assert evaluate_scan(104.0, is_us=True) is True
    assert scan_count == 3

    # 2. Di luar Sesi US (target: 5s)
    _last_gold_scan_time = 10.0
    scan_count = 0

    # T=10s -> Reset base
    # T=11s, 12s, 13s, 14s -> Skip
    for t in [11.0, 12.0, 13.0, 14.0]:
        assert evaluate_scan(t, is_us=False) is False
        assert scan_count == 0

    # T=15s -> Scan 1 (genap 5s)
    assert evaluate_scan(15.0, is_us=False) is True
    assert scan_count == 1


def test_all_sessions_1_second_scan():
    """Menguji bahwa saat disetel 1 detik semua sesi, scan berjalan setiap 1 detik tanpa skip."""
    gold_scan_sec = 1
    gold_scan_us_sec = 1
    enable_adaptive = False

    _last_gold_scan_time = 0.0
    scan_count = 0

    def mock_pipeline_run():
        nonlocal scan_count
        scan_count += 1

    def evaluate_scan(current_ts, is_us):
        nonlocal _last_gold_scan_time
        target_interval = gold_scan_us_sec if (enable_adaptive and is_us) else gold_scan_sec
        if target_interval > 1 and (current_ts - _last_gold_scan_time < (target_interval - 0.2)):
            return False
        _last_gold_scan_time = current_ts
        mock_pipeline_run()
        return True

    # Scan setiap 1 detik di Sesi Asia
    assert evaluate_scan(100.0, is_us=False) is True
    assert evaluate_scan(101.0, is_us=False) is True
    assert evaluate_scan(102.0, is_us=False) is True
    assert scan_count == 3

    # Scan setiap 1 detik di Sesi US
    assert evaluate_scan(103.0, is_us=True) is True
    assert evaluate_scan(104.0, is_us=True) is True
    assert scan_count == 5

