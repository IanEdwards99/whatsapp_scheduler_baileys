#!/usr/bin/env python3
"""
WhatsApp Scheduler - Unified Management CLI

Usage:
    python3 manage.py setup          # One-time setup
    python3 manage.py start          # Start driver + scheduler
    python3 manage.py web            # Start Flask UI (on-demand)
    python3 manage.py stop           # Stop all processes
    python3 manage.py status         # Show running processes
    python3 manage.py fresh-start    # Clear session + re-authenticate
    python3 manage.py update         # Pull latest code + reinstall deps
    python3 manage.py install-service  # Install systemd services (Linux)
"""

# === STDLIB ONLY at top level (must work before pip install) ===
import argparse
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.resolve()
VENV_DIR = PROJECT_DIR / "venv"
PIDS_FILE = PROJECT_DIR / "pids.json"
LOGS_DIR = PROJECT_DIR / "logs"
ENV_FILE = PROJECT_DIR / ".env"
QR_FILE = PROJECT_DIR / "qr_code.png"
SCHEDULES_DIR = PROJECT_DIR / "schedules"

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"

if IS_WINDOWS:
    VENV_PYTHON = VENV_DIR / "Scripts" / "python.exe"
    VENV_PIP = VENV_DIR / "Scripts" / "pip.exe"
else:
    VENV_PYTHON = VENV_DIR / "bin" / "python"
    VENV_PIP = VENV_DIR / "bin" / "pip"


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {level}: {msg}")


def log_to_file(msg):
    """Append to supervisor log."""
    LOGS_DIR.mkdir(exist_ok=True)
    with open(LOGS_DIR / "supervisor.log", "a") as f:
        f.write(f"[{datetime.now().isoformat()}] {msg}\n")


def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def is_pid_alive(pid):
    """Check if a process with given PID is running (cross-platform)."""
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False
    except SystemError:
        return False


def read_pids():
    try:
        return json.loads(PIDS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_pids(data):
    PIDS_FILE.write_text(json.dumps(data, indent=2))


def find_node():
    node = shutil.which("node")
    if not node:
        log("Node.js not found! Install from https://nodejs.org/", "ERROR")
        sys.exit(1)
    return node


def open_browser(url):
    """Open URL in default browser (cross-platform)."""
    try:
        if IS_WINDOWS:
            os.startfile(url)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass  # Not critical


def check_setup_done():
    """Verify that setup has been completed."""
    errors = []
    if not VENV_DIR.exists():
        errors.append("Python venv not found")
    if not (PROJECT_DIR / "node_modules").exists():
        errors.append("node_modules not found")
    if errors:
        log("Setup incomplete: " + ", ".join(errors), "ERROR")
        log("Run ./install (or: python3 manage.py setup) first.")
        sys.exit(1)


# ─────────────────────────────────────────────
# QR Code Delivery
# ─────────────────────────────────────────────

class QRWatcher(threading.Thread):
    """Watch for qr_code.png and deliver via email/telegram."""

    def __init__(self):
        super().__init__(daemon=True)
        self.stop_event = threading.Event()
        self._last_mtime = 0
        self._delivered = False

    def run(self):
        while not self.stop_event.is_set():
            if QR_FILE.exists():
                mtime = QR_FILE.stat().st_mtime
                if mtime != self._last_mtime:
                    self._last_mtime = mtime
                    self._delivered = False

                if not self._delivered:
                    time.sleep(1)  # Wait for file write to finish
                    self._deliver()
                    self._delivered = True
            self.stop_event.wait(2)

    def _deliver(self):
        print()
        log("QR CODE GENERATED - Scan to authenticate!")
        log(f"  View at: http://127.0.0.1:5001/qr_code.png")
        log(f"  File:    {QR_FILE}")
        log_to_file("QR code generated, delivering notifications")

        self._send_email()
        self._send_telegram()

    def _send_email(self):
        """Send QR code as email attachment using stdlib."""
        try:
            from dotenv import load_dotenv
            load_dotenv(ENV_FILE)
        except ImportError:
            pass

        user = os.environ.get("EMAIL_USER", "")
        passwd = os.environ.get("EMAIL_PASS", "")
        to = os.environ.get("EMAIL_TO", "")

        if not (user and passwd and to):
            return

        try:
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            from email.mime.image import MIMEImage

            msg = MIMEMultipart()
            msg["Subject"] = "[WhatsApp Scheduler] QR Code - Scan to Authenticate"
            msg["From"] = user
            msg["To"] = to

            body = MIMEText(
                "Your WhatsApp Scheduler needs authentication.\n"
                "Scan the attached QR code with WhatsApp on your phone:\n"
                "WhatsApp > Settings > Linked Devices > Link a Device\n\n"
                f"Or open: http://127.0.0.1:5001/qr_code.png",
                "plain",
            )
            msg.attach(body)

            with open(QR_FILE, "rb") as f:
                img = MIMEImage(f.read(), name="qr_code.png")
                msg.attach(img)

            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls()
                server.login(user, passwd)
                server.send_message(msg)

            log("  QR code emailed to " + to)
            log_to_file(f"QR code emailed to {to}")
        except Exception as e:
            log(f"  Email delivery failed: {e}", "WARN")

    def _send_telegram(self):
        """Send QR code via Telegram Bot API (raw HTTP, no library)."""
        try:
            from dotenv import load_dotenv
            load_dotenv(ENV_FILE)
        except ImportError:
            pass

        token = os.environ.get("TELEGRAM_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

        if not (token and chat_id):
            return

        try:
            import urllib.request
            import urllib.parse

            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            boundary = "----WhatsAppSchedulerBoundary"

            with open(QR_FILE, "rb") as f:
                photo_data = f.read()

            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
                f"{chat_id}\r\n"
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="caption"\r\n\r\n'
                f"WhatsApp Scheduler: Scan this QR code to authenticate\r\n"
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="photo"; filename="qr_code.png"\r\n'
                f"Content-Type: image/png\r\n\r\n"
            ).encode() + photo_data + f"\r\n--{boundary}--\r\n".encode()

            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            urllib.request.urlopen(req, timeout=10)
            log(f"  QR code sent via Telegram to chat {chat_id}")
            log_to_file(f"QR code sent via Telegram to chat {chat_id}")
        except Exception as e:
            log(f"  Telegram delivery failed: {e}", "WARN")

    def stop(self):
        self.stop_event.set()


# ─────────────────────────────────────────────
# Setup walkthroughs
# ─────────────────────────────────────────────

def _hr(char="─", width=60):
    print(char * width)


def _prompt_yes(question, default_yes=True):
    suffix = "[Y/n]" if default_yes else "[y/N]"
    while True:
        answer = input(f"{question} {suffix}: ").strip().lower()
        if not answer:
            return default_yes
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False


def setup_email_walkthrough():
    """Walk the user through Gmail app password setup. Returns (user, pass, to)."""
    print()
    _hr("═")
    print("  EMAIL NOTIFICATIONS (optional)")
    _hr("═")
    print()
    print("  Email is used to:")
    print("    • Deliver the WhatsApp QR code to your inbox on first run")
    print("    • Alert you when scheduled messages fail to send")
    print()
    print("  You can skip this and set it up later by editing .env.")
    print()

    if not _prompt_yes("  Configure email now?", default_yes=True):
        print("  Skipping email setup.")
        return "", "", ""

    print()
    _hr()
    print("  GMAIL APP PASSWORD — step-by-step")
    _hr()
    print()
    print("  Gmail requires a 16-character 'App Password' (not your normal")
    print("  password). This only works if 2-Factor Authentication is ON.")
    print()
    print("  1. Enable 2FA (if not already):")
    print("       https://myaccount.google.com/signinoptions/two-step-verification")
    print()
    print("  2. Generate an App Password:")
    print("       https://myaccount.google.com/apppasswords")
    print("       • App name: 'WhatsApp Scheduler' (or anything)")
    print("       • Click 'Create' — Google shows a 16-char code like:")
    print("           abcd efgh ijkl mnop")
    print("       • Copy it (spaces don't matter).")
    print()
    print("  3. Paste below. It won't be echoed for security.")
    print()

    email_user = input("  Gmail address: ").strip()
    if not email_user:
        print("  No address entered — skipping email.")
        return "", "", ""

    try:
        import getpass
        email_pass = getpass.getpass("  App Password (hidden): ").strip().replace(" ", "")
    except Exception:
        email_pass = input("  App Password: ").strip().replace(" ", "")

    if not email_pass:
        print("  No password entered — skipping email.")
        return "", "", ""

    print()
    email_to = input(f"  Send alerts to [{email_user}]: ").strip() or email_user
    print()
    print(f"  ✓ Email configured: {email_user} → {email_to}")
    return email_user, email_pass, email_to


def setup_telegram_walkthrough():
    """Walk the user through Telegram bot setup. Returns (token, chat_id)."""
    print()
    _hr("═")
    print("  TELEGRAM BOT (optional)")
    _hr("═")
    print()
    print("  A Telegram bot can:")
    print("    • Send the WhatsApp QR code to your phone instantly")
    print("    • Let you manage schedules from Telegram")
    print()
    print("  You can skip this and add it later by editing .env.")
    print()

    if not _prompt_yes("  Configure Telegram now?", default_yes=False):
        print("  Skipping Telegram setup.")
        return "", ""

    print()
    _hr()
    print("  TELEGRAM BOT — step-by-step")
    _hr()
    print()
    print("  STEP 1 — Create the bot")
    print("    a. Open Telegram, search for:  @BotFather")
    print("    b. Start a chat, send:         /newbot")
    print("    c. Follow prompts — choose a display name, then a")
    print("       username ending in 'bot' (e.g. MyScheduler_bot).")
    print("    d. BotFather replies with a token that looks like:")
    print("         123456789:ABCdefGHIjklMNOpqrsTUVwxyz-0123456789")
    print("    e. Copy that token.")
    print()

    token = input("  Paste Bot Token: ").strip()
    if not token:
        print("  No token entered — skipping Telegram.")
        return "", ""

    print()
    print("  STEP 2 — Find your Chat ID")
    print(f"    a. Open Telegram and MESSAGE YOUR NEW BOT (say 'hi').")
    print(f"       This is required — the bot can't find you otherwise.")
    print(f"    b. Press Enter below; we'll fetch the chat ID for you.")
    print()
    input("  Press Enter once you have messaged the bot... ")

    chat_id = ""
    try:
        import urllib.request
        import json as _json
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = _json.loads(resp.read().decode())
        if data.get("ok") and data.get("result"):
            for update in reversed(data["result"]):
                msg = update.get("message") or update.get("edited_message")
                if msg and msg.get("chat", {}).get("id"):
                    chat_id = str(msg["chat"]["id"])
                    name = msg["chat"].get("first_name") or msg["chat"].get("title") or "you"
                    print(f"  ✓ Found chat: {name} (ID: {chat_id})")
                    break
        if not chat_id:
            print("  Couldn't auto-detect chat ID. Did you message the bot?")
    except Exception as e:
        print(f"  Auto-detection failed ({e}).")

    if not chat_id:
        print()
        print("  Manual fallback: open this URL in a browser —")
        print(f"    https://api.telegram.org/bot{token}/getUpdates")
        print("  Look for 'chat':{'id': NUMBER}  and enter it below.")
        chat_id = input("  Chat ID: ").strip()

    if not chat_id:
        print("  No chat ID — skipping Telegram.")
        return token, ""

    print()
    print(f"  ✓ Telegram configured (chat ID: {chat_id})")
    return token, chat_id


# ─────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────

def cmd_setup(args):
    """One-time project setup."""
    log("Starting setup...")

    # 1. Check prerequisites
    node = shutil.which("node")
    npm = shutil.which("npm")
    python = sys.executable

    if not node or not npm:
        log("Node.js and npm are required.", "ERROR")
        log("Install from: https://nodejs.org/")
        sys.exit(1)

    node_ver = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
    major = int(node_ver.lstrip("v").split(".")[0])
    if major < 16:
        log(f"Node.js >= 16 required, found {node_ver}", "ERROR")
        sys.exit(1)
    log(f"Node.js {node_ver} OK")

    py_ver = platform.python_version()
    py_major, py_minor = int(py_ver.split(".")[0]), int(py_ver.split(".")[1])
    if py_major < 3 or (py_major == 3 and py_minor < 8):
        log(f"Python >= 3.8 required, found {py_ver}", "ERROR")
        sys.exit(1)
    log(f"Python {py_ver} OK")

    # 2. Create Python venv
    if not VENV_DIR.exists():
        log("Creating Python virtual environment...")
        subprocess.run([python, "-m", "venv", str(VENV_DIR)], check=True)
        log("  venv created")
    else:
        log("  venv already exists")

    # 3. Install Python deps
    log("Installing Python dependencies...")
    subprocess.run(
        [str(VENV_PIP), "install", "-r", str(PROJECT_DIR / "requirements.txt")],
        check=True,
    )

    # 4. Install Node deps
    if not (PROJECT_DIR / "node_modules").exists():
        log("Installing Node.js dependencies...")
        subprocess.run(["npm", "install"], cwd=str(PROJECT_DIR), check=True)
    else:
        log("  node_modules already exists, running npm install to update...")
        subprocess.run(["npm", "install"], cwd=str(PROJECT_DIR), check=True)

    # 5. Create directories
    SCHEDULES_DIR.mkdir(exist_ok=True)
    LOGS_DIR.mkdir(exist_ok=True)

    schedule_file = SCHEDULES_DIR / "schedule.json"
    if not schedule_file.exists():
        schedule_file.write_text("[]")

    history_file = SCHEDULES_DIR / "message_history.json"
    if not history_file.exists():
        history_file.write_text("[]")

    # 6. Create .env interactively if missing
    if not ENV_FILE.exists():
        email_user, email_pass, email_to = setup_email_walkthrough()
        telegram_token, telegram_chat_id = setup_telegram_walkthrough()

        env_content = f"""# WhatsApp Scheduler Configuration
EMAIL_USER={email_user}
EMAIL_PASS={email_pass}
EMAIL_TO={email_to}

# WhatsApp Driver
DRIVER_URL=http://127.0.0.1:5001

# Telegram Bot
TELEGRAM_TOKEN={telegram_token}
TELEGRAM_CHAT_ID={telegram_chat_id}
"""
        ENV_FILE.write_text(env_content)
        log(".env created")
    else:
        log(".env already exists")

    print()
    log("Setup complete!")
    print()
    print("  Next steps:")
    print("    ./whatsapp-start    Start driver + scheduler")
    print("    ./whatsapp-web      Open the web UI")
    print()


def cmd_start(args):
    """Start driver + scheduler with process supervision."""
    check_setup_done()

    # Check if already running
    pids = read_pids()
    if pids.get("driver", {}).get("pid") and is_pid_alive(pids["driver"]["pid"]):
        log("Driver is already running (PID {})".format(pids["driver"]["pid"]))
        log("Run ./whatsapp-stop first, or ./whatsapp-status to check.")
        sys.exit(1)

    if is_port_in_use(5001):
        log("Port 5001 is already in use!", "ERROR")
        sys.exit(1)

    LOGS_DIR.mkdir(exist_ok=True)
    log_to_file("=== Starting WhatsApp Scheduler ===")

    node = find_node()
    driver_log = open(LOGS_DIR / "driver.log", "a")
    scheduler_log = open(LOGS_DIR / "scheduler.log", "a")
    driver_proc = None
    scheduler_proc = None
    qr_watcher = QRWatcher()
    shutting_down = False

    def cleanup(signum=None, frame=None):
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        print()
        log("Shutting down...")
        log_to_file("Shutdown initiated")

        qr_watcher.stop()

        for name, proc in [("scheduler", scheduler_proc), ("driver", driver_proc)]:
            if proc and proc.poll() is None:
                log(f"  Stopping {name} (PID {proc.pid})...")
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    log(f"  Force killing {name}...")
                    proc.kill()

        driver_log.close()
        scheduler_log.close()

        if PIDS_FILE.exists():
            PIDS_FILE.unlink()

        log("Stopped.")
        log_to_file("Shutdown complete")
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, cleanup)

    # Start driver
    log("Starting WhatsApp driver...")
    driver_proc = subprocess.Popen(
        [node, "server.js"],
        cwd=str(PROJECT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        universal_newlines=True,
    )

    # Tee driver output to both terminal (so QR is visible) and driver.log
    def _tee_driver():
        try:
            for line in driver_proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                driver_log.write(line)
                driver_log.flush()
        except Exception:
            pass

    tee_thread = threading.Thread(target=_tee_driver, daemon=True)
    tee_thread.start()
    log(f"  Driver started (PID {driver_proc.pid})")
    log_to_file(f"Driver started PID={driver_proc.pid}")

    # Start QR watcher
    qr_watcher.start()

    # Write initial PIDs
    write_pids({
        "driver": {"pid": driver_proc.pid, "started_at": datetime.now().isoformat()},
        "supervisor": {"pid": os.getpid(), "started_at": datetime.now().isoformat()},
    })

    # Wait for driver to be ready
    log("Waiting for driver to connect...")
    max_wait = 300  # 5 minutes
    poll_interval = 3
    elapsed = 0
    driver_ready = False

    while elapsed < max_wait and not shutting_down:
        if driver_proc.poll() is not None:
            log("Driver process exited unexpectedly!", "ERROR")
            log(f"  Check logs: {LOGS_DIR / 'driver.log'}")
            cleanup()
            return

        try:
            import urllib.request
            resp = urllib.request.urlopen("http://127.0.0.1:5001/status", timeout=3)
            data = json.loads(resp.read())
            if data.get("ready"):
                driver_ready = True
                break
        except Exception:
            pass

        time.sleep(poll_interval)
        elapsed += poll_interval

        if elapsed % 30 == 0 and elapsed > 0:
            log(f"  Still waiting for authentication... ({elapsed}s)")

    if not driver_ready and not shutting_down:
        log("Driver did not become ready within 5 minutes.", "WARN")
        log("It may still be waiting for QR scan. Continuing anyway...")

    # Stop QR watcher once connected
    if driver_ready:
        qr_watcher.stop()
        log("Driver connected and authenticated!")
        log_to_file("Driver authenticated successfully")

    # Start scheduler
    log("Starting background scheduler...")
    scheduler_proc = subprocess.Popen(
        [str(VENV_PYTHON), "background_scheduler.py"],
        cwd=str(PROJECT_DIR),
        stdout=scheduler_log,
        stderr=subprocess.STDOUT,
    )
    log(f"  Scheduler started (PID {scheduler_proc.pid})")
    log_to_file(f"Scheduler started PID={scheduler_proc.pid}")

    # Update PIDs
    pids_data = read_pids()
    pids_data["scheduler"] = {"pid": scheduler_proc.pid, "started_at": datetime.now().isoformat()}
    write_pids(pids_data)

    log("All services running. Press Ctrl+C to stop.")
    print()

    # Supervision loop
    restart_count = {"driver": 0, "scheduler": 0}
    max_restarts = 5

    while not shutting_down:
        time.sleep(10)

        # Check driver
        if driver_proc.poll() is not None and not shutting_down:
            restart_count["driver"] += 1
            if restart_count["driver"] > max_restarts:
                log(f"Driver has crashed {max_restarts} times, giving up.", "ERROR")
                cleanup()
                return
            log(f"Driver crashed, restarting ({restart_count['driver']}/{max_restarts})...", "WARN")
            log_to_file(f"Driver crashed, restart #{restart_count['driver']}")
            driver_log = open(LOGS_DIR / "driver.log", "a")
            driver_proc = subprocess.Popen(
                [node, "server.js"],
                cwd=str(PROJECT_DIR),
                stdout=driver_log,
                stderr=subprocess.STDOUT,
            )
            pids_data = read_pids()
            pids_data["driver"] = {"pid": driver_proc.pid, "started_at": datetime.now().isoformat()}
            write_pids(pids_data)
            # Restart QR watcher for re-auth
            qr_watcher = QRWatcher()
            qr_watcher.start()

        # Check scheduler
        if scheduler_proc.poll() is not None and not shutting_down:
            restart_count["scheduler"] += 1
            if restart_count["scheduler"] > max_restarts:
                log(f"Scheduler has crashed {max_restarts} times, giving up.", "ERROR")
                cleanup()
                return
            log(f"Scheduler crashed, restarting ({restart_count['scheduler']}/{max_restarts})...", "WARN")
            log_to_file(f"Scheduler crashed, restart #{restart_count['scheduler']}")
            scheduler_log = open(LOGS_DIR / "scheduler.log", "a")
            scheduler_proc = subprocess.Popen(
                [str(VENV_PYTHON), "background_scheduler.py"],
                cwd=str(PROJECT_DIR),
                stdout=scheduler_log,
                stderr=subprocess.STDOUT,
            )
            pids_data = read_pids()
            pids_data["scheduler"] = {"pid": scheduler_proc.pid, "started_at": datetime.now().isoformat()}
            write_pids(pids_data)


def cmd_web(args):
    """Start Flask web UI on-demand."""
    check_setup_done()

    if is_port_in_use(5000):
        log("Port 5000 is already in use (Flask may already be running).", "WARN")
        open_browser("http://127.0.0.1:5000")
        return

    LOGS_DIR.mkdir(exist_ok=True)
    flask_log = open(LOGS_DIR / "flask.log", "a")

    log("Starting Flask web UI...")
    flask_proc = subprocess.Popen(
        [str(VENV_PYTHON), "app.py"],
        cwd=str(PROJECT_DIR),
        stdout=flask_log,
        stderr=subprocess.STDOUT,
    )

    # Update PIDs
    pids_data = read_pids()
    pids_data["flask"] = {"pid": flask_proc.pid, "started_at": datetime.now().isoformat()}
    write_pids(pids_data)

    time.sleep(2)
    if flask_proc.poll() is not None:
        log("Flask failed to start! Check logs/flask.log", "ERROR")
        return

    url = "http://127.0.0.1:5000"
    log(f"Flask running at {url}")
    open_browser(url)
    log("Press Ctrl+C to stop the web UI.")

    flask_stopping = False

    def cleanup(signum=None, frame=None):
        nonlocal flask_stopping
        if flask_stopping:
            return
        flask_stopping = True
        print()
        log("Stopping Flask...")
        flask_proc.terminate()
        try:
            flask_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            flask_proc.kill()
        flask_log.close()
        # Remove flask from PIDs
        pids_data = read_pids()
        pids_data.pop("flask", None)
        write_pids(pids_data)
        log("Flask stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    flask_proc.wait()


def cmd_stop(args):
    """Stop all running processes."""
    pids = read_pids()
    stopped_any = False

    for name in ["flask", "scheduler", "driver", "supervisor"]:
        info = pids.get(name, {})
        pid = info.get("pid")
        if pid and is_pid_alive(pid):
            log(f"Stopping {name} (PID {pid})...")
            try:
                os.kill(pid, signal.SIGTERM)
                # Wait for graceful shutdown
                for _ in range(50):  # 5 seconds
                    if not is_pid_alive(pid):
                        break
                    time.sleep(0.1)
                if is_pid_alive(pid):
                    log(f"  Force killing {name}...")
                    os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            stopped_any = True

    # Fallback: kill by process name
    if not IS_WINDOWS:
        for pattern in ["node server.js", "background_scheduler.py", "app.py"]:
            subprocess.run(
                ["pkill", "-f", pattern],
                capture_output=True,
            )

    if PIDS_FILE.exists():
        PIDS_FILE.unlink()

    if stopped_any:
        log("All processes stopped.")
    else:
        log("No running processes found.")


def cmd_status(args):
    """Show status of all processes."""
    pids = read_pids()

    print()
    print("  WhatsApp Scheduler Status")
    print("  " + "=" * 40)

    for name in ["driver", "scheduler", "flask", "supervisor"]:
        info = pids.get(name, {})
        pid = info.get("pid")
        started = info.get("started_at", "")
        alive = is_pid_alive(pid)
        status = "RUNNING" if alive else "STOPPED"
        marker = "+" if alive else "-"
        pid_str = f"PID {pid}" if pid else ""
        print(f"  [{marker}] {name:12s} {status:8s} {pid_str:10s} {started}")

    # Check driver connection
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://127.0.0.1:5001/status", timeout=3)
        data = json.loads(resp.read())
        connected = data.get("ready", False)
        print()
        print(f"  WhatsApp: {'Connected' if connected else 'Not connected (needs QR scan)'}")
        if not connected and QR_FILE.exists():
            print(f"  QR Code:  http://127.0.0.1:5001/qr_code.png")
    except Exception:
        print()
        print("  WhatsApp: Driver not reachable")

    print()


def cmd_fresh_start(args):
    """Clear session data and re-authenticate."""
    print()
    print("  This will delete your WhatsApp session.")
    print("  You will need to re-scan the QR code.")
    resp = input("  Continue? (y/N): ").strip().lower()
    if resp != "y":
        log("Aborted.")
        return

    # Stop everything first
    cmd_stop(args)
    time.sleep(2)

    # Clear session
    auth_dir = PROJECT_DIR / "baileys_auth_info"
    if auth_dir.exists():
        shutil.rmtree(auth_dir)
        log("Cleared baileys_auth_info/")

    if QR_FILE.exists():
        QR_FILE.unlink()
        log("Cleared qr_code.png")

    log("Session cleared. Run ./whatsapp-start to re-authenticate.")


def cmd_update(args):
    """Pull latest changes and reinstall dependencies."""
    log("Checking for updates...")

    # Git pull
    result = subprocess.run(
        ["git", "pull"],
        cwd=str(PROJECT_DIR),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log(f"git pull failed: {result.stderr}", "ERROR")
        sys.exit(1)

    if "Already up to date" in result.stdout:
        log("Already up to date.")
        return

    print(result.stdout.strip())
    log("Code updated. Reinstalling dependencies...")

    # Reinstall deps
    subprocess.run(
        [str(VENV_PIP), "install", "-r", str(PROJECT_DIR / "requirements.txt")],
        check=True,
    )
    subprocess.run(["npm", "install"], cwd=str(PROJECT_DIR), check=True)

    log("Update complete!")
    log("Restart services with: ./whatsapp-stop && ./whatsapp-start")


def cmd_install_service(args):
    """Generate and install systemd service files (Linux only)."""
    if not IS_LINUX:
        log("systemd services are only available on Linux.", "ERROR")
        sys.exit(1)

    import getpass
    user = getpass.getuser()
    node_path = find_node()

    systemd_dir = PROJECT_DIR / "systemd"
    systemd_dir.mkdir(exist_ok=True)

    # Driver service
    driver_service = f"""[Unit]
Description=WhatsApp Driver Server (Baileys)
After=network.target

[Service]
Type=simple
User={user}
WorkingDirectory={PROJECT_DIR}
ExecStart={node_path} server.js
Restart=on-failure
RestartSec=30
TimeoutStopSec=300
TimeoutStartSec=infinity
StartLimitIntervalSec=600
StartLimitBurst=5
MemoryHigh=650M
MemoryMax=800M
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""

    # Scheduler service
    scheduler_service = f"""[Unit]
Description=WhatsApp Background Scheduler
After=network.target whatsapp-driver.service
Requires=whatsapp-driver.service

[Service]
Type=simple
User={user}
WorkingDirectory={PROJECT_DIR}
Environment=PATH={VENV_DIR}/bin:/usr/local/bin:/usr/bin:/bin
EnvironmentFile=-/home/{user}/.whatsapp-scheduler-email
ExecStart={VENV_PYTHON} background_scheduler.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""

    # Flask service
    flask_service = f"""[Unit]
Description=WhatsApp Scheduler Flask Web UI
After=network.target whatsapp-driver.service

[Service]
Type=simple
User={user}
WorkingDirectory={PROJECT_DIR}
Environment=PATH={VENV_DIR}/bin:/usr/local/bin:/usr/bin:/bin
ExecStart={VENV_PYTHON} app.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""

    # Maintenance service + timer
    maintenance_service = f"""[Unit]
Description=WhatsApp Scheduler Daily Maintenance
After=network.target

[Service]
Type=oneshot
User=root
WorkingDirectory={PROJECT_DIR}
ExecStart={PROJECT_DIR}/daily_maintenance.sh
"""

    maintenance_timer = """[Unit]
Description=Run WhatsApp maintenance daily at 4 AM

[Timer]
OnCalendar=*-*-* 04:00:00
Persistent=true

[Install]
WantedBy=timers.target
"""

    files = {
        "whatsapp-driver.service": driver_service,
        "whatsapp-scheduler.service": scheduler_service,
        "whatsapp-flask.service": flask_service,
        "whatsapp-maintenance.service": maintenance_service,
        "whatsapp-maintenance.timer": maintenance_timer,
    }

    for name, content in files.items():
        (systemd_dir / name).write_text(content)
        log(f"  Generated {name}")

    print()
    log("Service files generated in systemd/")
    print()
    print("  To install, run:")
    print(f"    sudo cp {systemd_dir}/*.service {systemd_dir}/*.timer /etc/systemd/system/")
    print("    sudo systemctl daemon-reload")
    print()
    print("  To enable on boot:")
    print("    sudo systemctl enable whatsapp-driver whatsapp-scheduler")
    print()
    print("  To start:")
    print("    sudo systemctl start whatsapp-driver whatsapp-scheduler")
    print()
    print("  Flask is on-demand (don't enable it):")
    print("    sudo systemctl start whatsapp-flask   # when you need the web UI")
    print()


def cmd_uninstall(args):
    """Remove venv, node_modules, session, and (optionally) all data."""
    print()
    _hr("═")
    print("  UNINSTALL WhatsApp Scheduler")
    _hr("═")
    print()
    print("  This will remove:")
    print("    • Python virtual environment (venv/)")
    print("    • Node.js dependencies (node_modules/)")
    print("    • WhatsApp session data (baileys_auth_info/)")
    print("    • Process tracking (pids.json, *.lock)")
    print()
    print("  By default, your schedules and configuration are KEPT so you can")
    print("  reinstall later. You will be asked separately about deleting those.")
    print()

    if not _prompt_yes("  Proceed with uninstall?", default_yes=False):
        log("Aborted.")
        return

    # Stop any running processes first
    log("Stopping services...")
    try:
        cmd_stop(args)
    except SystemExit:
        pass
    time.sleep(2)

    # Core removals
    targets = [
        ("venv/", VENV_DIR),
        ("node_modules/", PROJECT_DIR / "node_modules"),
        ("baileys_auth_info/", PROJECT_DIR / "baileys_auth_info"),
        ("qr_code.png", QR_FILE),
        ("pids.json", PIDS_FILE),
    ]
    for label, path in targets:
        if path.exists():
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                log(f"  Removed {label}")
            except Exception as e:
                log(f"  Could not remove {label}: {e}", "WARN")

    # Lock files
    for lock in PROJECT_DIR.glob("**/*.lock"):
        try:
            lock.unlink()
        except Exception:
            pass

    print()
    print("  DELETE USER DATA?")
    print("    Schedules:      schedules/schedule.json")
    print("    Message history: schedules/message_history.json")
    print("    Configuration:   .env")
    print("    Logs:            logs/")
    print()

    if _prompt_yes("  Also delete schedules, history, .env, and logs?", default_yes=False):
        extras = [
            ("schedules/", SCHEDULES_DIR),
            (".env", ENV_FILE),
            ("logs/", LOGS_DIR),
        ]
        for label, path in extras:
            if path.exists():
                try:
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                    log(f"  Removed {label}")
                except Exception as e:
                    log(f"  Could not remove {label}: {e}", "WARN")
    else:
        print("  Keeping schedules, .env, and logs.")

    print()
    log("Uninstall complete.")
    print()
    print("  To fully remove the project, delete this folder:")
    print(f"    {PROJECT_DIR}")
    print()
    print("  To reinstall, run: ./install")
    print()


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="WhatsApp Scheduler Management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Quick start:
              ./install            One-time setup
              ./whatsapp-start     Start driver + scheduler
              ./whatsapp-web       Open the web UI
              ./whatsapp-stop      Stop everything
              ./update             Pull latest code + update deps
        """),
    )

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("setup", help="One-time project setup")
    sub.add_parser("start", help="Start driver + scheduler")
    sub.add_parser("web", help="Start Flask web UI (on-demand)")
    sub.add_parser("stop", help="Stop all processes")
    sub.add_parser("status", help="Show running processes")
    sub.add_parser("fresh-start", help="Clear session + re-authenticate")
    sub.add_parser("update", help="Pull latest code + reinstall deps")
    sub.add_parser("install-service", help="Install systemd services (Linux)")
    sub.add_parser("uninstall", help="Remove venv, deps, and session (keep schedules)")

    args = parser.parse_args()

    commands = {
        "setup": cmd_setup,
        "start": cmd_start,
        "web": cmd_web,
        "stop": cmd_stop,
        "status": cmd_status,
        "fresh-start": cmd_fresh_start,
        "update": cmd_update,
        "install-service": cmd_install_service,
        "uninstall": cmd_uninstall,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
