from unittest.mock import MagicMock, patch
import subprocess
from pathlib import Path
from scheduler.auto_updater import GitAutoUpdater


def test_git_auto_updater_no_update():
    updater = GitAutoUpdater(base_dir=Path("d:/bot saham"), branch="main", auto_restart=False)

    with patch("subprocess.run") as mock_run:
        # Mock git fetch
        mock_fetch = MagicMock(returncode=0, stdout="", stderr="")
        # Mock git rev-parse HEAD
        mock_head = MagicMock(returncode=0, stdout="abc1234\n", stderr="")
        # Mock git rev-parse origin/main
        mock_remote = MagicMock(returncode=0, stdout="abc1234\n", stderr="")

        mock_run.side_effect = [mock_fetch, mock_head, mock_remote]

        has_update, local_h, remote_h = updater.check_for_updates()
        assert has_update is False
        assert local_h == "abc1234"
        assert remote_h == "abc1234"

        # Check and pull should return False
        res = updater.check_and_pull()
        assert res is False


def test_git_auto_updater_with_update():
    mock_notifier = MagicMock()
    updater = GitAutoUpdater(base_dir=Path("d:/bot saham"), branch="main", auto_restart=False, notifier=mock_notifier)

    with patch("subprocess.run") as mock_run:
        # Mock git fetch
        mock_fetch = MagicMock(returncode=0, stdout="", stderr="")
        # Mock git rev-parse HEAD
        mock_head = MagicMock(returncode=0, stdout="abc1234\n", stderr="")
        # Mock git rev-parse origin/main
        mock_remote = MagicMock(returncode=0, stdout="def5678\n", stderr="")
        # Mock git rev-list --count
        mock_count = MagicMock(returncode=0, stdout="1\n", stderr="")
        # Mock git pull
        mock_pull = MagicMock(returncode=0, stdout="Updating abc1234..def5678\n", stderr="")
        # Mock git log
        mock_log = MagicMock(returncode=0, stdout="def5678 - feat: new trailing stop (selobrow)\n", stderr="")

        mock_run.side_effect = [mock_fetch, mock_head, mock_remote, mock_count, mock_pull, mock_log]

        has_update, local_h, remote_h = updater.check_for_updates()
        assert has_update is True

    # Now test full check_and_pull
    with patch("subprocess.run") as mock_run:
        mock_fetch = MagicMock(returncode=0, stdout="", stderr="")
        mock_head = MagicMock(returncode=0, stdout="abc1234\n", stderr="")
        mock_remote = MagicMock(returncode=0, stdout="def5678\n", stderr="")
        mock_count = MagicMock(returncode=0, stdout="1\n", stderr="")
        mock_pull = MagicMock(returncode=0, stdout="Updating abc1234..def5678\n", stderr="")
        mock_log = MagicMock(returncode=0, stdout="def5678 - feat: new trailing stop (selobrow)\n", stderr="")

        mock_run.side_effect = [mock_fetch, mock_head, mock_remote, mock_count, mock_pull, mock_log]

        res = updater.check_and_pull()
        assert res is True
        mock_notifier.send_message_sync.assert_called_once()
        args, _ = mock_notifier.send_message_sync.call_args
        assert "def5678 - feat: new trailing stop" in args[0]


def test_git_auto_updater_already_up_to_date():
    mock_notifier = MagicMock()
    updater = GitAutoUpdater(base_dir=Path("d:/bot saham"), branch="main", auto_restart=False, notifier=mock_notifier)

    with patch("subprocess.run") as mock_run:
        mock_fetch = MagicMock(returncode=0, stdout="", stderr="")
        mock_head = MagicMock(returncode=0, stdout="abc1234\n", stderr="")
        mock_remote = MagicMock(returncode=0, stdout="def5678\n", stderr="")
        mock_count = MagicMock(returncode=0, stdout="1\n", stderr="")
        mock_pull = MagicMock(returncode=0, stdout="Already up to date.\n", stderr="")

        mock_run.side_effect = [mock_fetch, mock_head, mock_remote, mock_count, mock_pull]

        res = updater.check_and_pull()
        assert res is False
        mock_notifier.send_message_sync.assert_not_called()


def test_git_auto_updater_local_ahead_no_pull():
    """Menguji saat commit lokal lebih baru dari remote (ahead), bot tidak boleh mencoba pull."""
    updater = GitAutoUpdater(base_dir=Path("d:/bot saham"), branch="main", auto_restart=False)

    with patch("subprocess.run") as mock_run:
        mock_fetch = MagicMock(returncode=0, stdout="", stderr="")
        mock_head = MagicMock(returncode=0, stdout="eda923c\n", stderr="")
        mock_remote = MagicMock(returncode=0, stdout="d21b487\n", stderr="")
        mock_count = MagicMock(returncode=0, stdout="0\n", stderr="")  # 0 commit di belakang remote

        mock_run.side_effect = [mock_fetch, mock_head, mock_remote, mock_count]

        has_update, local_h, remote_h = updater.check_for_updates()
        assert has_update is False
        assert local_h == "eda923c"
        assert remote_h == "d21b487"

        res = updater.check_and_pull()
        assert res is False

