import os
import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple

from config.settings import setup_logger

logger = setup_logger("auto_updater")


class GitAutoUpdater:
    """
    Auto-updater lokal yang memantau repository GitHub secara berkala.
    Jika terdeteksi commit baru di remote branch (misal: perubahan dari device collab):
    1. Melakukan git pull secara otomatis.
    2. Mengirim notifikasi detail commit ke Telegram Owner.
    3. Me-restart proses bot secara mulus agar kodingan baru langsung aktif di RAM.
    """

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        branch: str = "main",
        auto_restart: bool = True,
        notifier: Optional[object] = None,
    ):
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
        self.branch = branch
        self.auto_restart = auto_restart
        self.notifier = notifier
        self._is_updating = False
        self.initial_head = self._get_current_head()

    def _get_current_head(self) -> str:
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(self.base_dir),
                capture_output=True,
                text=True,
                timeout=10,
            )
            return proc.stdout.strip()
        except Exception:
            return ""

    def check_for_updates(self) -> Tuple[bool, str, str]:
        """
        Melakukan git fetch dan membandingkan commit hash lokal vs remote.
        Returns:
            (has_update, local_hash, remote_hash)
        """
        try:
            # 1. Fetch remote branch
            fetch_res = subprocess.run(
                ["git", "fetch", "origin", self.branch],
                cwd=str(self.base_dir),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if fetch_res.returncode != 0:
                logger.warning(f"Git fetch gagal: {fetch_res.stderr.strip()}")
                return False, "", ""

            # 2. Local commit hash
            local_proc = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(self.base_dir),
                capture_output=True,
                text=True,
                timeout=10,
            )
            local_hash = local_proc.stdout.strip()

            # 3. Remote commit hash
            remote_proc = subprocess.run(
                ["git", "rev-parse", f"origin/{self.branch}"],
                cwd=str(self.base_dir),
                capture_output=True,
                text=True,
                timeout=10,
            )
            remote_hash = remote_proc.stdout.strip()

            if not local_hash or not remote_hash:
                return False, local_hash, remote_hash

            has_update = local_hash != remote_hash
            return has_update, local_hash, remote_hash
        except subprocess.TimeoutExpired:
            logger.warning("Git check timeout saat menghubungi GitHub.")
            return False, "", ""
        except Exception as e:
            logger.error(f"Error saat memeriksa update Git: {e}")
            return False, "", ""

    def apply_pull(self) -> Tuple[bool, str]:
        """
        Menjalankan 'git pull origin <branch>' dan mengambil ringkasan commit terbaru.
        Returns:
            (success, message_or_commit_info)
        """
        try:
            pull_proc = subprocess.run(
                ["git", "pull", "origin", self.branch],
                cwd=str(self.base_dir),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if pull_proc.returncode != 0:
                err_msg = pull_proc.stderr.strip() or pull_proc.stdout.strip()
                logger.error(f"Git pull gagal: {err_msg}")
                return False, err_msg

            # Ambil pesan commit terbaru
            log_proc = subprocess.run(
                ["git", "log", "-1", "--pretty=format:%h - %s (%an)"],
                cwd=str(self.base_dir),
                capture_output=True,
                text=True,
                timeout=10,
            )
            commit_info = log_proc.stdout.strip() or "Update berhasil ditarik."
            return True, commit_info
        except Exception as e:
            logger.error(f"Error saat apply git pull: {e}")
            return False, str(e)

    def notify_telegram(self, title: str, message: str) -> None:
        """Mengirim notifikasi Telegram ke owner jika notifier tersedia."""
        if not self.notifier:
            return
        try:
            full_msg = f"🔄 <b>{title}</b>\n\n{message}"
            if hasattr(self.notifier, "send_message_sync"):
                self.notifier.send_message_sync(full_msg)
            elif hasattr(self.notifier, "send_message"):
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(self.notifier.send_message(full_msg))
                    else:
                        loop.run_until_complete(self.notifier.send_message(full_msg))
                except Exception:
                    pass
        except Exception as ex:
            logger.warning(f"Gagal mengirim notifikasi auto-updater ke Telegram: {ex}")

    def restart_process(self) -> None:
        """
        Me-restart proses bot saat ini secara mulus di Windows.
        Proses baru dijalankan via subprocess, lalu proses saat ini ditutup.
        """
        logger.info("🔄 Me-restart proses bot Master agar kode terbaru langsung aktif...")
        try:
            python_bin = sys.executable
            args = [python_bin] + sys.argv
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NEW_CONSOLE
            # Spawn proses baru yang independen
            subprocess.Popen(args, cwd=str(self.base_dir), creationflags=creationflags)
            time.sleep(1.0)
            os._exit(0)
        except Exception as e:
            logger.error(f"Gagal me-restart proses bot: {e}")

    def manual_update(self, force: bool = False) -> Tuple[bool, str, bool]:
        """
        Melakukan git pull manual berdasarkan perintah pengguna (/update atau /gitpull).
        Returns:
            (success, message_or_commit_info, restarted)
        """
        try:
            has_update, local_h, remote_h = self.check_for_updates()
            if not has_update and not force:
                log_proc = subprocess.run(
                    ["git", "log", "-1", "--pretty=format:%h - %s (%an)"],
                    cwd=str(self.base_dir),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                commit_info = log_proc.stdout.strip() or "Repository sudah sinkron dengan origin/main."
                return True, commit_info, False

            success, commit_info = self.apply_pull()
            if success:
                if self.auto_restart:
                    import threading
                    threading.Timer(2.0, self.restart_process).start()
                return True, commit_info, True
            else:
                return False, commit_info, False
        except Exception as e:
            logger.error(f"Error saat manual update Git: {e}")
            return False, str(e), False

    def check_and_pull(self) -> bool:
        """
        Fungsi utama yang dipanggil oleh cron job / scheduler berkala (tiap 5 menit).
        """
        if self._is_updating:
            logger.debug("Auto-pull sedang berjalan, melewati siklus ini...")
            return False

        self._is_updating = True
        try:
            has_update, local_h, remote_h = self.check_for_updates()
            if not has_update:
                if self.initial_head and local_h and (local_h != self.initial_head):
                    logger.info(f"🚀 Terdeteksi kodingan lokal berubah ({self.initial_head[:7]} -> {local_h[:7]}). Me-restart proses bot...")
                    self.initial_head = local_h
                    if self.auto_restart:
                        self.restart_process()
                    return True
                logger.debug(f"Git repo up-to-date ({local_h[:7] if local_h else 'ok'}). Tidak ada kodingan baru.")
                return False

            logger.info(f"🚀 Terdeteksi kodingan baru di GitHub ({local_h[:7]} -> {remote_h[:7]}). Memulai git pull...")
            success, commit_info = self.apply_pull()

            if success:
                logger.info(f"✅ Git pull berhasil! Commit: {commit_info}")
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                msg = (
                    f"Master Server mendeteksi kodingan baru dari Device Collab!\n\n"
                    f"📝 <b>Commit Terbaru:</b>\n<code>{commit_info}</code>\n\n"
                    f"⏰ <b>Waktu:</b> {now_str} WIB\n"
                )
                if self.auto_restart:
                    msg += "🚀 <i>Me-restart bot otomatis dalam 1 detik agar fitur baru langsung aktif di memori...</i>"

                self.notify_telegram("[AUTO-UPDATE GITHUB MASTER]", msg)

                if self.auto_restart:
                    self.restart_process()
                return True
            else:
                logger.error(f"❌ Gagal melakukan git pull: {commit_info}")
                self.notify_telegram(
                    "[AUTO-UPDATE GAGAL]",
                    f"Terdeteksi kodingan baru namun gagal melakukan git pull.\nDetail error:\n<code>{commit_info}</code>"
                )
                return False
        finally:
            self._is_updating = False
