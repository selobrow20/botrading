import os
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Dict
import yaml
from dotenv import load_dotenv

# Root Directory Proyek
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables dari .env (bisa di root atau di config/)
env_path_root = BASE_DIR / ".env"
env_path_config = BASE_DIR / "config" / ".env"
if env_path_root.exists():
    load_dotenv(dotenv_path=env_path_root)
elif env_path_config.exists():
    load_dotenv(dotenv_path=env_path_config)
else:
    load_dotenv()


def load_config(config_path: Path | str | None = None) -> Dict[str, Any]:
    """Membaca file konfigurasi config.yaml"""
    if config_path is None:
        config_path = BASE_DIR / "config" / "config.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"File konfigurasi tidak ditemukan: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config or {}


def setup_logger(name: str = "stock_bot", log_level: str | None = None) -> logging.Logger:
    """Mengatur logger dengan output ke konsol dan file harian."""
    config = load_config()
    logging_cfg = config.get("logging", {})

    level_name = log_level or logging_cfg.get("level", "INFO")
    level = getattr(logging, level_name.upper(), logging.INFO)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Hindari duplikasi handler jika fungsi dipanggil berulang
    if logger.handlers:
        return logger

    # Format log
    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s:%(lineno)d] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File Handler (Daily Rotating)
    log_dir_name = logging_cfg.get("log_dir", "logs")
    log_dir = BASE_DIR / log_dir_name
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "stock_bot.log"
    retention_days = logging_cfg.get("retention_days", 14)
    file_handler = TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",
        interval=1,
        backupCount=retention_days,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
