import os
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
import pandas as pd
from config.settings import BASE_DIR, load_config, setup_logger

logger = setup_logger("storage")


SUPERADMIN_CHAT_ID = "8754997836"


class StockStorage:
    """Manajer SQLite untuk menyimpan dan membaca data pasar, sinyal, dan backtest."""

    def __init__(self, db_path: Optional[str | Path] = None):
        if db_path is None:
            env_db = os.getenv("DATABASE_PATH")
            if env_db:
                self.db_path = Path(env_db) if Path(env_db).is_absolute() else (BASE_DIR / env_db)
            else:
                cfg = load_config()
                rel_path = cfg.get("storage", {}).get("db_path", "data/stock_data.db")
                self.db_path = BASE_DIR / rel_path
        else:
            self.db_path = Path(db_path)

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()

    @contextmanager
    def _get_connection(self):
        """Membuat koneksi SQLite dengan row_factory dictionary dan auto-close."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_tables(self) -> None:
        """Inisialisasi skema tabel jika belum ada."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Tabel 1: OHLCV Data
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ohlcv_data (
                    ticker TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    datetime TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    PRIMARY KEY (ticker, interval, datetime)
                );
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_ohlcv_query 
                ON ohlcv_data (ticker, interval, datetime ASC);
            """)

            # Tabel 2: Sinyal Trading History (dengan Tracking TP/SL & Win/Lose)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    price REAL NOT NULL,
                    reasons TEXT,
                    candle_time TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_notified INTEGER DEFAULT 0,
                    take_profit_price REAL,
                    stop_loss_price REAL,
                    outcome TEXT DEFAULT 'OPEN',
                    exit_price REAL,
                    exit_time TEXT,
                    pnl_pct REAL
                );
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_signals_ticker 
                ON signals (ticker, strategy_name, candle_time);
            """)

            # Auto-migration untuk tabel signals lama
            for col_name, col_def in [
                ("take_profit_price", "REAL"),
                ("stop_loss_price", "REAL"),
                ("outcome", "TEXT DEFAULT 'OPEN'"),
                ("exit_price", "REAL"),
                ("exit_time", "TEXT"),
                ("pnl_pct", "REAL"),
            ]:
                try:
                    cursor.execute(f"ALTER TABLE signals ADD COLUMN {col_name} {col_def};")
                except Exception:
                    pass

            # Tabel 3: Hasil Backtest
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS backtest_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_name TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    initial_capital REAL NOT NULL,
                    final_equity REAL NOT NULL,
                    total_trades INTEGER NOT NULL,
                    win_rate REAL NOT NULL,
                    profit_factor REAL,
                    max_drawdown REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Tabel 4: Pengguna Terotorisasi (Access Control / Whitelist)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS authorized_users (
                    chat_id TEXT PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    requested_at TEXT NOT NULL,
                    approved_at TEXT
                );
            """)
            conn.commit()
            logger.debug(f"Database dan tabel berhasil diinisialisasi di {self.db_path}")

    def save_ohlcv(self, ticker: str, interval: str, df: pd.DataFrame) -> int:
        """
        Menyimpan DataFrame OHLCV ke SQLite dengan pola upsert (INSERT OR REPLACE).
        DataFrame harus memiliki kolom/index datetime, serta Open, High, Low, Close, Volume.
        """
        if df.empty:
            logger.warning(f"DataFrame kosong untuk {ticker} ({interval}), tidak ada data yang disimpan.")
            return 0

        df_to_save = df.copy()

        # Pastikan kolom datetime tersedia baik di index atau kolom biasa
        if "datetime" not in df_to_save.columns:
            if isinstance(df_to_save.index, pd.DatetimeIndex):
                df_to_save["datetime"] = df_to_save.index.strftime("%Y-%m-%d %H:%M:%S")
            elif "Date" in df_to_save.columns:
                df_to_save["datetime"] = pd.to_datetime(df_to_save["Date"]).dt.strftime("%Y-%m-%d %H:%M:%S")
            elif "Datetime" in df_to_save.columns:
                df_to_save["datetime"] = pd.to_datetime(df_to_save["Datetime"]).dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                raise ValueError("DataFrame harus memiliki DatetimeIndex atau kolom Date/Datetime/datetime.")

        # Standardisasi nama kolom case-insensitive
        rename_map = {}
        for col in df_to_save.columns:
            c_lower = str(col).lower()
            if c_lower == "open":
                rename_map[col] = "open"
            elif c_lower == "high":
                rename_map[col] = "high"
            elif c_lower == "low":
                rename_map[col] = "low"
            elif c_lower == "close":
                rename_map[col] = "close"
            elif c_lower == "volume":
                rename_map[col] = "volume"

        df_to_save = df_to_save.rename(columns=rename_map)
        required_cols = ["datetime", "open", "high", "low", "close", "volume"]
        missing = [c for c in required_cols if c not in df_to_save.columns]
        if missing:
            raise ValueError(f"Kolom wajib hilang di DataFrame: {missing}")

        records = []
        ticker_clean = ticker.upper()
        interval_clean = interval.lower()

        for _, row in df_to_save[required_cols].iterrows():
            records.append((
                ticker_clean,
                interval_clean,
                str(row["datetime"]),
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                float(row["volume"]),
            ))

        query = """
            INSERT OR REPLACE INTO ohlcv_data 
            (ticker, interval, datetime, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(query, records)
            conn.commit()

        logger.info(f"Berhasil menyimpan {len(records)} baris data OHLCV untuk {ticker_clean} ({interval_clean}).")
        return len(records)

    def load_ohlcv(
        self,
        ticker: str,
        interval: str = "1d",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Membaca data OHLCV dari SQLite menjadi DataFrame dengan DatetimeIndex
        dan kolom standar: Open, High, Low, Close, Volume.
        """
        ticker_clean = ticker.upper()
        interval_clean = interval.lower()

        query = """
            SELECT datetime, open, high, low, close, volume
            FROM ohlcv_data
            WHERE ticker = ? AND interval = ?
        """
        params: List[Any] = [ticker_clean, interval_clean]

        if start_date:
            query += " AND datetime >= ?"
            params.append(start_date)
        if end_date:
            query += " AND datetime <= ?"
            params.append(end_date)

        query += " ORDER BY datetime ASC"

        if limit:
            query += f" LIMIT {int(limit)}"

        with self._get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=params)

        if df.empty:
            logger.debug(f"Data tidak ditemukan di database untuk {ticker_clean} ({interval_clean}).")
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

        df["datetime"] = pd.to_datetime(df["datetime"])
        df.set_index("datetime", inplace=True)
        df.rename(
            columns={
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "volume": "Volume",
            },
            inplace=True,
        )
        return df

    def get_latest_price_any_interval(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Mendapatkan harga dan tanggal candle terakhir untuk suatu saham dari interval apa pun."""
        ticker_clean = ticker.upper()
        if not ticker_clean.endswith(".JK") and not "." in ticker_clean:
            ticker_clean = f"{ticker_clean}.JK"

        query = """
            SELECT datetime, close, interval, volume
            FROM ohlcv_data
            WHERE ticker = ?
            ORDER BY datetime DESC
            LIMIT 1
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (ticker_clean,))
            row = cursor.fetchone()

        if row:
            return dict(row)
        return None

    def save_signal(
        self,
        ticker: str,
        strategy_name: str,
        signal_type: str,
        price: float,
        reasons: List[str] | str,
        candle_time: str,
        is_notified: bool = False,
        take_profit_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
    ) -> int:
        """Menyimpan riwayat sinyal baru ke database dengan target profit & stop loss."""
        if isinstance(reasons, list):
            reasons_json = json.dumps(reasons, ensure_ascii=False)
        else:
            reasons_json = json.dumps([str(reasons)], ensure_ascii=False)

        query = """
            INSERT INTO signals 
            (ticker, strategy_name, signal_type, price, reasons, candle_time, is_notified, take_profit_price, stop_loss_price, outcome)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                query,
                (
                    ticker.upper(),
                    strategy_name,
                    signal_type.upper(),
                    float(price),
                    reasons_json,
                    str(candle_time),
                    1 if is_notified else 0,
                    float(take_profit_price) if take_profit_price is not None else None,
                    float(stop_loss_price) if stop_loss_price is not None else None,
                ),
            )
            conn.commit()
            signal_id = cursor.lastrowid

        logger.info(f"Sinyal {signal_type} untuk {ticker} tersimpan (ID: {signal_id}).")
        return signal_id

    def update_open_signals_outcome(self, ticker: str, df: pd.DataFrame) -> int:
        """
        Mengevaluasi sinyal terbuka (outcome = 'OPEN') terhadap bar-bar candle terbaru.
        Jika harga menyentuh TP -> WIN, jika menyentuh SL -> LOSE.
        Mengembalikan jumlah sinyal yang diselesaikan (resolved).
        """
        if df.empty or "High" not in df.columns or "Low" not in df.columns:
            return 0

        clean_ticker = ticker.upper()
        query = """
            SELECT id, ticker, signal_type, price, candle_time, take_profit_price, stop_loss_price
            FROM signals
            WHERE ticker = ? AND outcome = 'OPEN' AND signal_type IN ('BUY', 'SELL')
            AND take_profit_price IS NOT NULL AND stop_loss_price IS NOT NULL
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (clean_ticker,))
            open_signals = [dict(r) for r in cursor.fetchall()]

        if not open_signals:
            return 0

        resolved_count = 0
        is_gold = any(k in clean_ticker for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])

        df_eval = df.copy()
        if not isinstance(df_eval.index, pd.DatetimeIndex):
            df_eval.index = pd.to_datetime(df_eval.index)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            for sig in open_signals:
                sig_id = sig["id"]
                sig_type = sig["signal_type"]
                entry_price = float(sig["price"])
                tp = float(sig["take_profit_price"])
                sl = float(sig["stop_loss_price"])
                try:
                    sig_time = pd.to_datetime(sig["candle_time"])
                except Exception:
                    continue

                subsequent_bars = df_eval[df_eval.index > sig_time]
                if subsequent_bars.empty:
                    continue

                for bar_time, bar in subsequent_bars.iterrows():
                    high = float(bar["High"])
                    low = float(bar["Low"])
                    outcome = None
                    exit_price = None
                    pnl_pct = 0.0

                    if sig_type == "BUY":
                        if high >= tp:
                            outcome = "WIN"
                            exit_price = tp
                            pnl_pct = round(((tp - entry_price) / entry_price) * 100.0, 2)
                        elif low <= sl:
                            outcome = "LOSE"
                            exit_price = sl
                            pnl_pct = round(((sl - entry_price) / entry_price) * 100.0, 2)
                    elif sig_type == "SELL" and is_gold:
                        if low <= tp:
                            outcome = "WIN"
                            exit_price = tp
                            pnl_pct = round(((entry_price - tp) / entry_price) * 100.0, 2)
                        elif high >= sl:
                            outcome = "LOSE"
                            exit_price = sl
                            pnl_pct = round(((entry_price - sl) / entry_price) * 100.0, 2)
                    elif sig_type == "SELL" and not is_gold:
                        # Saham IDX SELL: Jika harga turun di bawah entry, profit teramankan (WIN)
                        if low <= tp:
                            outcome = "WIN"
                            exit_price = tp
                            pnl_pct = round(((entry_price - tp) / entry_price) * 100.0, 2)
                        elif high >= sl:
                            outcome = "LOSE"
                            exit_price = sl
                            pnl_pct = round(((entry_price - sl) / entry_price) * 100.0, 2)

                    if outcome:
                        exit_time_str = bar_time.strftime("%Y-%m-%d %H:%M:%S")
                        cursor.execute("""
                            UPDATE signals
                            SET outcome = ?, exit_price = ?, exit_time = ?, pnl_pct = ?
                            WHERE id = ?
                        """, (outcome, exit_price, exit_time_str, pnl_pct, sig_id))
                        resolved_count += 1
                        logger.info(
                            f"🎯 Sinyal #{sig_id} {sig_type} {clean_ticker} terselesaikan: "
                            f"{outcome} @ {exit_price} (PnL: {pnl_pct:+.2f}%) pada {exit_time_str}"
                        )
                        break

            conn.commit()

        return resolved_count

    def get_win_rate_stats(self, ticker: Optional[str] = None) -> Dict[str, Any]:
        """
        Menghitung ringkasan statistik performa Win Rate & Lose Rate dari seluruh sinyal.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if ticker:
                cursor.execute("""
                    SELECT outcome, pnl_pct, ticker, signal_type
                    FROM signals
                    WHERE ticker = ? AND signal_type IN ('BUY', 'SELL')
                """, (ticker.upper(),))
            else:
                cursor.execute("""
                    SELECT outcome, pnl_pct, ticker, signal_type
                    FROM signals
                    WHERE signal_type IN ('BUY', 'SELL')
                """)
            rows = [dict(r) for r in cursor.fetchall()]

        total_signals = len(rows)
        win_count = sum(1 for r in rows if r.get("outcome") == "WIN")
        lose_count = sum(1 for r in rows if r.get("outcome") == "LOSE")
        open_count = sum(1 for r in rows if r.get("outcome") == "OPEN")
        expired_count = sum(1 for r in rows if r.get("outcome") == "EXPIRED")

        completed = win_count + lose_count
        win_rate = round((win_count / completed) * 100.0, 1) if completed > 0 else 0.0
        lose_rate = round((lose_count / completed) * 100.0, 1) if completed > 0 else 0.0

        pnl_values = [float(r["pnl_pct"]) for r in rows if r.get("pnl_pct") is not None]
        total_pnl = round(sum(pnl_values), 2)
        avg_pnl = round(total_pnl / completed, 2) if completed > 0 else 0.0

        # Statistik khusus Gold
        gold_rows = [r for r in rows if any(k in r["ticker"].upper() for k in ["GC=F", "XAUUSD", "GOLD", "EMAS"])]
        gold_win = sum(1 for r in gold_rows if r.get("outcome") == "WIN")
        gold_lose = sum(1 for r in gold_rows if r.get("outcome") == "LOSE")
        gold_comp = gold_win + gold_lose
        gold_wr = round((gold_win / gold_comp) * 100.0, 1) if gold_comp > 0 else 0.0

        # Statistik khusus Saham IDX
        idx_rows = [r for r in rows if r not in gold_rows]
        idx_win = sum(1 for r in idx_rows if r.get("outcome") == "WIN")
        idx_lose = sum(1 for r in idx_rows if r.get("outcome") == "LOSE")
        idx_comp = idx_win + idx_lose
        idx_wr = round((idx_win / idx_comp) * 100.0, 1) if idx_comp > 0 else 0.0

        return {
            "total_signals": total_signals,
            "completed": completed,
            "win_count": win_count,
            "lose_count": lose_count,
            "open_count": open_count,
            "expired_count": expired_count,
            "win_rate": win_rate,
            "win_rate_pct": win_rate,
            "lose_rate": lose_rate,
            "lose_rate_pct": lose_rate,
            "total_pnl": total_pnl,
            "avg_pnl": avg_pnl,
            "gold_stats": {
                "total": len(gold_rows),
                "completed": gold_comp,
                "win": gold_win,
                "lose": gold_lose,
                "win_rate": gold_wr,
            },
            "idx_stats": {
                "total": len(idx_rows),
                "completed": idx_comp,
                "win": idx_win,
                "lose": idx_lose,
                "win_rate": idx_wr,
            },
        }

    def get_last_signal(self, ticker: str, strategy_name: str) -> Optional[Dict[str, Any]]:
        """Mendapatkan sinyal terakhir yang tercatat untuk suatu saham dan strategi."""
        query = """
            SELECT * FROM signals
            WHERE ticker = ? AND strategy_name = ?
            ORDER BY candle_time DESC, id DESC
            LIMIT 1
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (ticker.upper(), strategy_name))
            row = cursor.fetchone()

        if row is None:
            return None

        result = dict(row)
        try:
            result["reasons"] = json.loads(result["reasons"])
        except Exception:
            pass
        return result

    def get_recent_signals(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Mengambil N riwayat sinyal terakhir untuk command /lasthistory."""
        query = """
            SELECT * FROM signals
            ORDER BY id DESC
            LIMIT ?
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (limit,))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            item = dict(r)
            try:
                item["reasons"] = json.loads(item["reasons"])
            except Exception:
                pass
            results.append(item)
        return results

    def save_backtest_result(
        self,
        strategy_name: str,
        ticker: str,
        start_date: str,
        end_date: str,
        initial_capital: float,
        final_equity: float,
        total_trades: int,
        win_rate: float,
        profit_factor: Optional[float],
        max_drawdown: float,
    ) -> int:
        """Menyimpan ringkasan metrik hasil backtesting."""
        query = """
            INSERT INTO backtest_results
            (strategy_name, ticker, start_date, end_date, initial_capital, 
             final_equity, total_trades, win_rate, profit_factor, max_drawdown)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                query,
                (
                    strategy_name,
                    ticker.upper(),
                    start_date,
                    end_date,
                    initial_capital,
                    final_equity,
                    total_trades,
                    win_rate,
                    profit_factor,
                    max_drawdown,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    # ----------------------------------------------------
    # SISTEM HAK AKSES & OTORISASI PENGGUNA (WHITELIST)
    # ----------------------------------------------------

    def register_or_get_user(self, chat_id: str, username: str = "", full_name: str = "") -> str:
        """Mendaftarkan pengguna baru (status pending) atau mengembalikan status jika sudah ada."""
        chat_id_str = str(chat_id).strip()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM authorized_users WHERE chat_id = ?", (chat_id_str,))
            row = cursor.fetchone()
            if row:
                return str(row["status"])

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                INSERT INTO authorized_users (chat_id, username, full_name, status, requested_at)
                VALUES (?, ?, ?, 'pending', ?)
            """, (chat_id_str, username or "", full_name or "", now_str))
            return "pending"

    def is_user_authorized(self, chat_id: str, admin_id: Optional[str] = None) -> bool:
        """Memeriksa apakah pengguna diizinkan menggunakan bot."""
        chat_id_str = str(chat_id).strip()
        if chat_id_str in [SUPERADMIN_CHAT_ID, "8754997836"]:
            return True
        if admin_id and chat_id_str == str(admin_id).strip():
            return True
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM authorized_users WHERE chat_id = ?", (chat_id_str,))
            row = cursor.fetchone()
            if row and row["status"] == "approved":
                return True
        return False

    def approve_user(self, chat_id: str) -> bool:
        """Menyetujui akses pengguna."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        chat_id_str = str(chat_id).strip()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE authorized_users 
                SET status = 'approved', approved_at = ? 
                WHERE chat_id = ?
            """, (now_str, chat_id_str))
            if cursor.rowcount == 0:
                cursor.execute("""
                    INSERT INTO authorized_users (chat_id, username, full_name, status, requested_at, approved_at)
                    VALUES (?, '', 'Trader', 'approved', ?, ?)
                """, (chat_id_str, now_str, now_str))
            conn.commit()
            return True

    def reject_user(self, chat_id: str) -> bool:
        """Menolak atau mencabut akses pengguna."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE authorized_users 
                SET status = 'rejected' 
                WHERE chat_id = ?
            """, (str(chat_id).strip(),))
            return cursor.rowcount > 0

    def get_approved_chat_ids(self, admin_id: Optional[str] = None) -> List[str]:
        """Daftar chat ID yang aktif diizinkan menerima sinyal."""
        approved = {SUPERADMIN_CHAT_ID, "8754997836"}
        if admin_id and str(admin_id).strip():
            approved.add(str(admin_id).strip())
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT chat_id FROM authorized_users WHERE status = 'approved'")
            for r in cursor.fetchall():
                approved.add(str(r["chat_id"]).strip())
        return list(approved)

    def list_all_users(self) -> List[Dict[str, Any]]:
        """Daftar seluruh pengguna yang pernah meminta akses bot."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT chat_id, username, full_name, status, requested_at, approved_at 
                FROM authorized_users 
                ORDER BY requested_at DESC
            """)
            return [dict(r) for r in cursor.fetchall()]

