# WhatsApp Scheduler (Baileys)

A cross-platform WhatsApp message and poll scheduler with web UI. Schedule messages and polls to contacts or groups with recurring options, full history tracking, and automatic delivery monitoring.

Works on Linux, macOS, Windows (WSL or native), and Raspberry Pi.

## Quick Start

### Prerequisites

- **Node.js** >= 20 ([nodejs.org](https://nodejs.org/))
- **Python** >= 3.9

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

## Raspberry Pi deployment

Run these commands from the project directory on the Pi. Run `./install` first on a fresh checkout.

| Command | What it does |
| --- | --- |
| `python3 manage.py deploy` | Installs dependencies, installs systemd units, and starts the driver and scheduler at boot. |
| `python3 manage.py status` | Shows systemd and script processes and whether WhatsApp is connected. |
| `python3 manage.py start` | Starts the installed services. On a checkout without services, starts the foreground scripts. |
| `python3 manage.py stop` | Stops the services and any script processes started by the CLI. |
| `python3 manage.py start --script` | Starts the foreground driver and scheduler after the services have stopped. This uses the same WhatsApp session and queue. |
| `python3 manage.py update` | Pulls the current branch with a fast-forward and redeploys installed services. |

`./whatsapp-web` opens Flask on demand and works while the systemd scheduler is running.
The web UI and driver listen on the Pi's loopback interface. To use Flask remotely,
run the following on your computer and open [the scheduler](http://127.0.0.1:5000) in your browser.

```bash
ssh -L 5000:127.0.0.1:5000 iedwards@raspberrypi
cd ~/development/whatsapp_scheduler_baileys
./whatsapp-web
```

Use `python3 manage.py web --service` to keep Flask running after the SSH session ends.
The daily systemd timer checks the driver HTTP endpoint and restarts it if it stops responding.

## Scheduling with Telegram and timezones

Set `TELEGRAM_CHAT_ID` to your private chat ID. Use **Edit Schedule** or `/edit`,
choose an active schedule, then choose the field to change. Use `/add` to create a
schedule and `/cancel` to exit a prompt.

Choose an IANA timezone such as `Africa/Johannesburg` in the web form or Telegram.
Recurring schedules keep their clock time in the chosen timezone. For example,
08:30 in Johannesburg is 07:30 in Amsterdam in winter and 08:30 in summer.
Changing only a schedule's timezone in Telegram keeps its clock time and changes
the instant it will send. Existing schedules without a timezone use the server's
local time.

YouTube video and channel live links can include a WhatsApp thumbnail. A channel
live link may show the channel image until YouTube publishes an active stream.
Messages still send if the preview is unavailable.

## Scheduling a WhatsApp Status

Choose **WhatsApp Status** in the web form or use **Schedule Status** (`/addstatus`)
in Telegram. Paste one YouTube video or channel livestream link and enter 1–50
viewers using international phone numbers that start with `+`. Then choose a
date, time, timezone, and repeat setting. Edit the link or viewers later with
`/edit` or the web form.

The selected viewers are used for that post. The scheduler leaves your phone's
Status privacy settings alone. WhatsApp's acknowledgement confirms that it
accepted the post. Visibility still depends on the viewer's WhatsApp account.

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
- Check Node.js version: `node --version` (needs >= 20)
- Check logs: `cat logs/driver.log`
