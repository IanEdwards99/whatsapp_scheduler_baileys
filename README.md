# WhatsApp Scheduler (Baileys)

A cross-platform WhatsApp message and poll scheduler with web UI. Schedule messages and polls to contacts or groups with recurring options, full history tracking, and automatic delivery monitoring.

Works on Linux, macOS, Windows (WSL or native), and Raspberry Pi.

## Quick Start

### Prerequisites

- **Node.js** >= 16 ([nodejs.org](https://nodejs.org/))
- **Python** >= 3.8

### Install

```bash
git clone <your-repo-url>
cd whatsapp_driver_baileys
./install          # Linux/Mac
install.bat        # Windows
```

This creates a Python venv, installs all dependencies, and prompts for optional email/Telegram config.

### Start

```bash
./whatsapp-start   # Linux/Mac
whatsapp-start.bat # Windows
```

On first run, a QR code is generated. Scan it with WhatsApp on your phone (Settings > Linked Devices > Link a Device). If email or Telegram is configured, the QR code is sent automatically.

Once authenticated, the background scheduler starts and processes all pending schedules.

### Manage Schedules (Web UI)

```bash
./whatsapp-web     # Linux/Mac
whatsapp-web.bat   # Windows
```

Opens a web interface at `http://localhost:5000` where you can:
- Add/edit/delete scheduled messages and polls
- Send messages manually
- View message history and statistics

Press Ctrl+C to stop the web UI when done.

### Stop

```bash
./whatsapp-stop    # Linux/Mac
whatsapp-stop.bat  # Windows
```

### Update

```bash
./update           # Linux/Mac
update.bat         # Windows
```

Pulls latest code from git and reinstalls dependencies.

## Architecture

Three independent processes supervised by a single manager:

```
manage.py (supervisor)
  ├── node server.js          # Baileys WhatsApp driver (port 5001)
  ├── background_scheduler.py # Checks schedules every 30s, sends via driver API
  └── app.py                  # Flask web UI (port 5000, on-demand)
```

**Data flow:**
```
User -> Flask UI -> schedules/schedule.json <- Scheduler -> Driver API -> WhatsApp
                           |
                    message_history.json
```

### Why Baileys?

- **No browser**: Direct WebSocket connection to WhatsApp (no Chromium/Puppeteer)
- **Low memory**: ~50MB vs ~800MB for browser-based drivers
- **Fast startup**: Connects in seconds, not minutes
- **Reliable**: Handles reconnection, session persistence, and multi-device

## Project Structure

```
whatsapp_driver_baileys/
├── manage.py                  # CLI engine (all commands)
├── server.js                  # Baileys WhatsApp driver (port 5001)
├── app.py                     # Flask web UI (port 5000)
├── background_scheduler.py    # Background schedule processor
├── scheduler_core.py          # Scheduling logic + file locking
├── message_history.py         # Message tracking (10MB auto-prune)
├── email_notifications.py     # Email alerts on failures
├── telegram_bot.py            # Telegram bot integration
│
├── install / install.bat      # One-time setup
├── whatsapp-start / .bat      # Start driver + scheduler
├── whatsapp-web / .bat        # Start Flask UI
├── whatsapp-stop / .bat       # Stop everything
├── update / update.bat        # Pull updates + reinstall deps
│
├── templates/                 # Web UI templates
├── static/                    # CSS/JS
├── schedules/                 # schedule.json + message_history.json
├── logs/                      # driver.log, scheduler.log, flask.log
├── baileys_auth_info/         # WhatsApp session (auto-created)
├── systemd/                   # Systemd service files (Linux)
├── package.json               # Node.js dependencies
├── requirements.txt           # Python dependencies
└── .env                       # Configuration (email, Telegram, etc.)
```

## Configuration (.env)

Created during `./install`. All fields are optional:

```env
# Email alerts + QR code delivery (Gmail)
EMAIL_USER=your-email@gmail.com
EMAIL_PASS=your-app-password
EMAIL_TO=your-email@gmail.com

# WhatsApp driver URL
DRIVER_URL=http://127.0.0.1:5001

# Telegram bot (for QR delivery + schedule management)
TELEGRAM_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id
```

For Gmail, use an [App Password](https://myaccount.google.com/apppasswords), not your regular password.

## Raspberry Pi Production Deployment

For always-on deployment (e.g., RPi 3B+), use systemd:

```bash
python3 manage.py install-service
```

This generates systemd units with auto-detected paths. Then:

```bash
sudo cp systemd/*.service systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable whatsapp-driver whatsapp-scheduler
sudo systemctl start whatsapp-driver whatsapp-scheduler
```

The Flask web UI is on-demand:
```bash
sudo systemctl start whatsapp-flask   # When you need it
sudo systemctl stop whatsapp-flask    # When done
```

Daily maintenance runs at 4 AM via timer (health checks, memory management).

## Schedule Types

### Messages
```json
{
  "type": "message",
  "contact": "Group Name or +1234567890",
  "message": "Hello!",
  "time": "14:30",
  "recurring": "daily"
}
```

### Polls
```json
{
  "type": "poll",
  "contact": "Group Name",
  "question": "What day works?",
  "options": ["Monday", "Tuesday", "Wednesday"],
  "allow_multi_select": true,
  "recurring": "weekly"
}
```

Recurring options: `daily`, `weekly`, `monthly`, or `null` for one-time.

## Troubleshooting

### Check status
```bash
python3 manage.py status
```

### View logs
```bash
cat logs/driver.log
cat logs/scheduler.log
cat logs/supervisor.log
```

### Re-authenticate (new QR code)
```bash
python3 manage.py fresh-start
./whatsapp-start
```

### Driver won't connect
- Delete `baileys_auth_info/` and restart to get a fresh QR code
- Check Node.js version: `node --version` (needs >= 16)
- Check logs: `cat logs/driver.log`
