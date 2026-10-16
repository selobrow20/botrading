"""
BOTRADING DESKTOP LAUNCHER
Executable entry point for Windows Desktop:
- Automatically starts dashboard server silently (if stopped)
- Automatically starts trading bot engine 'main.py run-all' silently (if stopped)
- Launches dedicated native application window (Chromium App Mode: Edge / Chrome)
- 100% turnkey single double-click startup
"""

import os
import sys
import time
import subprocess
import urllib.request
import webbrowser

PORT = 8080
SERVER_URL = f"http://127.0.0.1:{PORT}"

def get_base_dir():
    """Resolve correct project root directory whether running as script or frozen .exe."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()

def get_python_bin():
    """Find virtualenv Python executable."""
    venv_python = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")
    if os.path.exists(venv_python):
        return venv_python
    return sys.executable

def is_server_running():
    try:
        with urllib.request.urlopen(f"{SERVER_URL}/api/network_info", timeout=2.0) as res:
            return res.status == 200
    except Exception:
        return False

def start_backend():
    if is_server_running():
        return True

    python_bin = get_python_bin()
    server_script = os.path.join(BASE_DIR, "dashboard_server.py")
    if not os.path.exists(server_script):
        return False

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW | 0x08000000  # DETACHED_PROCESS

    try:
        subprocess.Popen(
            [python_bin, server_script],
            cwd=BASE_DIR,
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception as e:
        print(f"Error launching backend: {e}")

    # Wait for server to come online
    for _ in range(25):
        time.sleep(0.5)
        if is_server_running():
            return True
    return False

def is_bot_running():
    try:
        import psutil
        for p in psutil.process_iter(["name", "cmdline"]):
            cmd = p.info.get("cmdline") or []
            if any("main.py" in str(arg) for arg in cmd):
                return True
    except Exception:
        pass
    return False

def start_bot():
    if is_bot_running():
        return True

    python_bin = get_python_bin()
    bot_script = os.path.join(BASE_DIR, "main.py")
    if not os.path.exists(bot_script):
        return False

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW | 0x08000000  # DETACHED_PROCESS

    try:
        subprocess.Popen(
            [python_bin, bot_script, "run-all"],
            cwd=BASE_DIR,
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return True
    except Exception as e:
        print(f"Error launching bot: {e}")
    return False

def launch_native_window():
    # Common paths for Edge and Chrome on Windows
    edge_paths = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
    ]
    chrome_paths = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]

    browser_bin = None
    for p in edge_paths + chrome_paths:
        if os.path.exists(p):
            browser_bin = p
            break

    if browser_bin:
        # Launch borderless, native desktop window
        args = [
            browser_bin,
            f"--app={SERVER_URL}",
            "--window-size=1440,920",
            "--window-position=50,50"
        ]
        try:
            subprocess.Popen(args)
            return
        except Exception:
            pass

    # Fallback to default browser
    webbrowser.open(SERVER_URL)

def main():
    start_backend()
    start_bot()
    launch_native_window()

if __name__ == "__main__":
    main()
