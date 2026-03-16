# WhatsApp Scheduler with open-wa

A production-ready WhatsApp message and poll scheduler with web interface, perfect for Raspberry Pi deployment. Schedule messages and polls to contacts or groups with recurring options, full message history tracking, and automatic delivery monitoring.

**Last updated: January 2025**

## Why open-wa?

- **Faster**: Uses WAPI (WhatsApp Web API) instead of full Selenium WebDriver
- **Lighter**: Reduced memory and CPU footprint (~200MB vs ~1GB)
- **Better for Pi**: Optimized for resource-constrained devices like Raspberry Pi 3B+
- **Headless**: Can run without display server
- **Session Persistence**: Automatic session rehydration (no repeated QR scans)
- **Native Polls**: Supports WhatsApp native poll UI for groups

## Project Structure

```
whatsapp_scheduler_openwa/
├── server.js                  # Node.js WhatsApp driver (port 5001)
├── app.py                     # Flask web UI (port 5000)
├── scheduler_core.py          # Core scheduling logic with file locking
├── background_scheduler.py    # Standalone scheduler process
├── message_history.py         # Message tracking with 10MB auto-pruning
├── process_manager.py         # Process supervision & auto-restart
├── package.json               # Node.js dependencies (@open-wa/wa-automate)
├── requirements.txt           # Python dependencies (Flask, requests)
├── templates/                 # Jinja2 HTML templates
│   ├── index.html             # Schedule list with delete buttons
│   ├── add_schedule.html      # Add new schedule form
│   ├── send_now.html          # Manual send interface
│   ├── overview.html          # Schedule overview
│   └── history.html           # Message history with stats
├── static/                    # CSS/JS/images
├── schedules/                 # Schedule and history storage
│   ├── schedule.json          # Active schedules
│   └── message_history.json   # Sent message log (auto-created)
├── systemd/                   # Systemd service files (optional)
├── start_all.sh               # Start driver, scheduler, and Flask
├── stop_all.sh                # Stop all services
├── setup_logs.sh              # Create logs directory
└── test_system.py             # System test script
```

## Features

✅ **Message Scheduling**: Schedule text messages to contacts or groups  
✅ **Poll Support**: Send native WhatsApp polls to groups (with interactive fallbacks for private chats)  
✅ **Status Tracking**: Real-time tracking of pending, completed, and failed deliveries  
✅ **Recurring Schedules**: Auto-recurring daily, weekly, or monthly schedules  
✅ **Message History**: Complete delivery tracking with 10MB auto-pruning  
✅ **File Locking**: Thread-safe operations with `fcntl` to prevent race conditions  
✅ **Group Name Resolution**: Type group names instead of cryptic JIDs  
✅ **Web Interface**: Beautiful Flask UI for schedule management  
✅ **Background Scheduler**: Independent scheduler process (no Flask dependency)  
✅ **Error Recovery**: Resilient to crashes and connection issues  
✅ **Statistics Dashboard**: View send success rates and delivery metrics

## Architecture

This application uses a **three-process architecture** for reliability and separation of concerns:

1. **Node.js Driver (server.js)** - Port 5001
   - Manages WhatsApp Web connection via `@open-wa/wa-automate`
   - Exposes HTTP API for sending messages and polls
   - Handles session persistence (no repeated QR scans)
   - Resolves group names to JIDs

2. **Python Background Scheduler (background_scheduler.py)**
   - Runs independently of Flask (can restart Flask without affecting scheduling)
   - Checks `schedules/schedule.json` every 10 seconds
   - Sends pending schedules via driver HTTP API
   - Logs all sends to message history
   - Updates recurring schedules automatically

3. **Flask Web UI (app.py)** - Port 5000
   - Web interface for schedule management
   - Manual send interface
   - Message history dashboard with statistics
   - Reads/writes schedules with file locking

**Data Flow:**
```
User → Flask UI → schedule.json ← Background Scheduler → Driver API → WhatsApp
                       ↓
                message_history.json (tracking & stats)
```

## Setup

### Prerequisites

- **Node.js** >= 16.0.0 (tested with v16.x, v18.x, v20.x)
- **Python** >= 3.8 (tested with 3.8, 3.10, 3.12)
- **Chromium or Chrome** browser (for WhatsApp Web automation)
- **WhatsApp account** with active phone number

### Installation (General Linux)

1. **Clone or download this repository:**
   ```bash
   cd /path/to/your/projects
   git clone <repo-url> whatsapp_scheduler_openwa
   cd whatsapp_scheduler_openwa
   ```

2. **Install Node.js dependencies:**
   ```bash
   npm install
   ```
   
   This installs `@open-wa/wa-automate` and `express`.

3. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
   
   This installs Flask, requests, and other required packages.

4. **Create required directories:**
   ```bash
   mkdir -p schedules logs
   ```

5. **Make scripts executable:**
   ```bash
   chmod +x start_all.sh stop_all.sh setup_logs.sh
   ```

6. **First-time WhatsApp authentication:**
   ```bash
   node server.js
   ```
   
   - A QR code will appear in the terminal
   - Open WhatsApp on your phone
   - Go to Settings → Linked Devices → Link a Device
   - Scan the QR code
   - Session will be saved to `whatsapp_scheduler.data.json`
   - Future runs will reuse this session (no QR needed)

## Running

### Option 1: Manual Start (Development)

**Terminal 1 - Driver Server:**
```bash
node server.js
```

**Terminal 2 - Background Scheduler:**
```bash
python3 background_scheduler.py
```

**Terminal 3 - Flask App:**
```bash
python3 app.py
```

Visit `http://localhost:5000` in your browser.

### Option 2: Helper Scripts (Recommended for Testing)

**Start all services:**
```bash
./start_all.sh
```

This starts the driver server, background scheduler, and Flask app in the background.  
Logs are written to `logs/driver.log`, `logs/scheduler.log`, and `logs/flask.log`.

**Stop all services:**
```bash
./stop_all.sh
```

### Option 3: Process Manager (Auto-Restart on Crash)

**Single Command:**
```bash
python3 process_manager.py
```

This starts and supervises both the driver server and background scheduler with automatic restart on crash.  
Start Flask separately if needed:
```bash
python3 app.py
```

### Option 4: Systemd Services (Production)

Systemd services run your processes in the background, survive reboots, and restart automatically on crashes.

#### Initial Setup

**1. Copy service files to systemd:**
```bash
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
```

**2. First-time QR Authentication:**

Before enabling services, you need to authenticate once:
```bash
# Start driver manually first
node server.js
```
Then access `http://<your-ip>:5001/qr_code.png` in a browser and scan the QR code with your phone. Once authenticated, stop the server (Ctrl+C) and proceed.

**3. Enable services to start on boot:**
```bash
# Enable driver and scheduler to always run
sudo systemctl enable whatsapp-driver whatsapp-scheduler

# Optional: Enable Flask too, or leave disabled for manual starts
sudo systemctl disable whatsapp-flask
```

**4. Start the services:**
```bash
sudo systemctl start whatsapp-driver
sudo systemctl start whatsapp-scheduler
# Start Flask only if enabled or when needed
sudo systemctl start whatsapp-flask
```

#### Recommended Setup

For most users, the **driver** and **scheduler** should always run, but the **Flask web UI** only needs to run when adding or editing schedules:

| Service | On Boot | Purpose |
|---------|---------|---------|
| `whatsapp-driver` | ✅ enabled | Always running - WhatsApp connection |
| `whatsapp-scheduler` | ✅ enabled | Always running - Sends scheduled messages |
| `whatsapp-flask` | ❌ disabled | Start manually when editing schedules |

#### Starting/Stopping Flask Manually

```bash
# When you want to add or edit schedules:
sudo systemctl start whatsapp-flask
# Then visit http://<your-ip>:5000

# When done editing:
sudo systemctl stop whatsapp-flask

# Or just leave it running - it uses minimal resources
```

#### Common Commands

```bash
# Check status
sudo systemctl status whatsapp-driver
sudo systemctl status whatsapp-scheduler
sudo systemctl status whatsapp-flask

# Restart a service
sudo systemctl restart whatsapp-driver

# Stop a service
sudo systemctl stop whatsapp-driver

# View live logs
sudo journalctl -u whatsapp-driver -f

# View last 100 log lines
sudo journalctl -u whatsapp-driver -n 100

# View logs since boot
sudo journalctl -u whatsapp-driver -b
```

#### After Editing Service Files

If you modify the `.service` files in the `systemd/` folder:
```bash
# Copy updated files
sudo cp systemd/*.service /etc/systemd/system/

# Tell systemd to re-read the files (required!)
sudo systemctl daemon-reload

# Restart affected services
sudo systemctl restart whatsapp-driver
```

#### Troubleshooting

**Service won't stop (hangs):**
```bash
sudo systemctl kill whatsapp-driver
sudo pkill -9 chromium
```

**QR code not appearing after fresh start:**
```bash
# Check if screenshot is available as fallback
curl http://<your-ip>:5001/qr_screenshot.png

# Or check the logs
sudo journalctl -u whatsapp-driver -n 50
```

**Session expired (need to re-authenticate):**
```bash
./fresh_start.sh  # Clears session data
sudo systemctl restart whatsapp-driver
# Then scan QR at http://<your-ip>:5001/qr_code.png
```

## API Endpoints

### Driver Server (port 5001)

**GET `/status`**  
Health check for driver readiness.
```bash
curl http://localhost:5001/status
# Returns: {"status": "ok", "ready": true}
```

**GET `/get_groups`**  
List all WhatsApp groups with JIDs.
```bash
curl http://localhost:5001/get_groups
# Returns: [{"name": "Family", "id": "120363...@g.us", "members": 5}, ...]
```

**POST `/send_message`**  
Send text message to contact or group.
```bash
curl -X POST http://localhost:5001/send_message \
  -H "Content-Type: application/json" \
  -d '{"contact": "+1 555 123 4567", "message": "Hello!"}'
# Returns: {"status": "ok"}
```

**POST `/send_poll`**  
Send poll (native for groups, fallback for private chats).
```bash
curl -X POST http://localhost:5001/send_poll \
  -H "Content-Type: application/json" \
  -d '{
    "contact": "Family",
    "question": "Where should we meet?",
    "options": ["Home", "Park", "Restaurant"]
  }'
# Returns: {"status": "ok", "method": "poll"}  # or "buttons" or "list"
```

**Poll Behavior:**
- **Groups** (`@g.us` JID): Native WhatsApp poll UI
- **Private chats with ≤3 options**: Interactive buttons (tap to reply)
- **Private chats with >3 options**: List message (select from menu)

### Flask App (port 5000)

**GET `/`**  
Main schedule list page.

**GET `/add`**  
Add new schedule form.

**POST `/add`**  
Submit new schedule.  
Form data: `type`, `contact`, `message`/`question`/`options`, `time`, `recurring`

**GET `/send_now`**  
Manual send interface.

**POST `/send_now`**  
Send message or poll immediately (bypasses scheduler).

**GET `/overview`**  
Full schedule overview with status.

**GET `/history`**  
Message history dashboard with statistics.

**DELETE `/delete/<index>`**  
Remove schedule by index.

### Telegram Bot (telegram_bot.py)

Interact with the scheduler directly from Telegram without needing the web UI.

**Setup**:
1. Get a bot token from BotFather (`@BotFather`) on Telegram.
2. Add your token to the `.env` file:
   ```env
   TELEGRAM_TOKEN=your_bot_token_here
   ```
3. Run the bot script:
   ```bash
   python3 telegram_bot.py
   ```

**Available Commands**:
- `/list` - View all upcoming schedules
- `/add <contact> | <message> | <YYYY-MM-DDTHH:MM> | [recurring]` - Add a new schedule
- `/delete <index>` - Delete a schedule by its index

## Schedule Format

Schedules are stored in `schedules/schedule.json`:

```json
[
  {
    "type": "message",
    "contact": "+1 555 123 4567",
    "message": "Hello!",
    "time": "14:30",
    "recurring": "daily",
    "status": "pending",
    "next_run": "2025-01-15T14:30:00",
    "last_run": null,
    "attempts": 0,
    "created_at": "2025-01-15T10:00:00"
  },
  {
    "type": "poll",
    "contact": "Family",
    "question": "Pizza night?",
    "options": ["Yes", "No", "Maybe"],
    "time": "18:00",
    "recurring": null,
    "status": "pending",
    "next_run": "2025-01-15T18:00:00",
    "last_run": null,
    "attempts": 0,
    "created_at": "2025-01-15T12:00:00"
  }
]
```

**Field Descriptions:**

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | `"message"` or `"poll"` |
| `contact` | string | Phone number, WhatsApp name, group name, or JID |
| `message` | string | Text message content (for type=message) |
| `question` | string | Poll question (for type=poll) |
| `options` | array | Poll options (for type=poll) |
| `time` | string | HH:MM format (24-hour) |
| `recurring` | string/null | `null`, `"daily"`, `"weekly"`, `"monthly"` |
| `status` | string | `"pending"`, `"completed"`, or `"failed"` |
| `next_run` | string | ISO datetime of next scheduled run |
| `last_run` | string/null | ISO datetime of last execution |
| `attempts` | integer | Number of send attempts |
| `created_at` | string | ISO datetime of schedule creation |

**Status Values:**
- `pending` - Waiting to be sent (only these are processed)
- `completed` - Successfully sent
- `failed` - Send attempt failed

**Recurring Options:**
- `null` or `""` - Send once, then mark completed
- `"daily"` - Repeat every 24 hours
- `"weekly"` - Repeat every 7 days
- `"monthly"` - Repeat every 30 days

**Recurring Behavior:**
1. Schedule runs at specified time
2. If successful, `status` → `"completed"`, `last_run` updated
3. `next_run` calculated (current time + interval)
4. `status` → `"pending"` for next occurrence
5. Process repeats indefinitely

## Testing

Run the comprehensive test script:

```bash
python3 test_system.py
```

This will test:
- Driver server connection
- Group name resolution
- Message sending to contact
- Message sending to group
- Poll sending
- Schedule creation and status tracking
- Recurring schedule logic

## How It Works

### Status Tracking
- All schedules start with `status: "pending"`
- Background scheduler only processes schedules with `status == "pending"`
- On successful send: `status` → `"completed"`, `last_run` updated
- On failed send: `status` → `"failed"`, `attempts` incremented
- This prevents duplicate sends and enables retry logic

### Recurring Logic
1. Recurring schedule reaches scheduled time
2. Background scheduler sends the message/poll
3. On success:
   - `last_run` = current ISO datetime
   - `next_run` = current time + interval (daily/weekly/monthly)
   - `status` = `"completed"` → `"pending"` (ready for next occurrence)
4. Scheduler uses `now >= next_run` comparison (robust, not brittle)
5. Only processes schedules with `status == "pending"` (prevents re-triggering)
6. Automatically handles missed schedules (if system was down)

**Example:** Daily schedule at 14:30
- First run: 2025-01-15 14:30:00
- After send: `next_run` = 2025-01-16 14:30:00, `status` = "pending"
- Next check at 14:30:15 sees `now >= next_run` → sends again
- Process repeats indefinitely

### File Locking
- Uses Python `fcntl` (Linux file locking) to prevent race conditions
- All access to `schedule.json` and `message_history.json` wrapped in lock
- Flask and background scheduler can safely read/write simultaneously
- Locks automatically released on process exit or exception
- Prevents corrupted JSON from concurrent writes

### Message History Tracking
- Every sent message/poll logged to `schedules/message_history.json`
- Includes: timestamp, type, contact, content, status, metadata
- Metadata tracks: source (manual/scheduled), recurring type, scheduled time
- Auto-prunes when file exceeds 10MB (keeps newest 50%)
- Statistics: total sent, success rate, failed count
- Accessible via Flask `/history` route with visual dashboard

### Group Name Resolution
1. User enters group name (e.g., "Family")
2. Scheduler calls driver `/get_groups` endpoint
3. Driver returns all groups with names and JIDs
4. Case-insensitive match finds correct JID (e.g., "120363...@g.us")
5. Message sent to resolved JID
6. If no match, sends to original contact string (falls back gracefully)

## Notes

- **First run**: QR code scan required; subsequent runs reuse saved session
- **Session persistence**: Stored in `whatsapp_scheduler.data.json` and `_IGNORE_whatsapp_scheduler/`
- **Contact formats**: Phone numbers (+1 555 123 4567), names (Family), or JIDs (120363...@g.us)
- **Group resolution**: Type group names; scheduler auto-resolves to JIDs via driver API
- **File locking**: Prevents race conditions between Flask and background scheduler
- **Background scheduler**: Independent of Flask; checks every 10 seconds (configurable in `background_scheduler.py`)
- **Message history**: Auto-prunes at 10MB; view stats and recent sends at `/history`
- **Poll limitations**: Native polls only work in groups; private chats use interactive buttons/lists
- **Timezone**: All timestamps use system local time
- **Process management**: Use `process_manager.py` for auto-restart on crash with exponential backoff

## Troubleshooting

**Driver won't start:**
- Check Node.js version: `node --version` (>= 16.0.0)
- Check if Chromium installed: `/usr/bin/chromium-browser --version`
- Check logs: `tail -f logs/driver.log` or `journalctl -u whatsapp-driver -f`

**Schedules not sending:**
- Verify driver ready: `curl http://localhost:5001/status`
- Check background scheduler running: `ps aux | grep background_scheduler`
- Check schedule file: `cat schedules/schedule.json`
- Check scheduler logs: `tail -f logs/scheduler.log`

**Group messages failing:**
- Fetch group JID: `node get_groups.mjs`
- Use exact group name or JID in schedule
- Check group name resolution in logs

**File lock issues:**
- Ensure processes run as same user
- Check file permissions on `schedules/schedule.json`
- Look for stale lock files: `ls -la schedules/*.lock`

**Process manager issues:**
- Check if ports are already in use: `lsof -i :5001` and `lsof -i :5000`
- Kill existing processes: `./stop_all.sh`
- Restart: `python3 process_manager.py`

## Migration from Selenium Version

This version maintains the same Flask interface but uses open-wa backend for better performance on Raspberry Pi 3B+.

**Key Differences:**
- Replaced Selenium with open-wa for lighter footprint
- Added status tracking for schedules
- Added recurring schedule support
- Added file locking for race condition prevention
- Added process management for auto-recovery
- Improved error handling and logging

## Development

**Run tests:**
```bash
python3 test_system.py
```

**View real-time logs:**
```bash
tail -f logs/driver.log logs/scheduler.log logs/flask.log
```

**Check schedule status:**
```bash
cat schedules/schedule.json | jq
```

**Manual testing via API:**
```bash
# Check status
curl http://localhost:5001/status

# Get groups
curl http://localhost:5001/get_groups

# Send message
curl -X POST http://localhost:5001/send_message \
  -H "Content-Type: application/json" \
  -d '{"contact": "+1 555 123 4567", "message": "Test"}'
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly with `test_system.py`
5. Submit a pull request

---

## Raspberry Pi 3B+ Setup Guide

Complete setup instructions for deploying WhatsApp Scheduler on Raspberry Pi 3 Model B+ from scratch.

### Why Raspberry Pi 3B+?

- **Low power**: ~2-3W idle, ~5-6W under load
- **Always-on**: Perfect for 24/7 scheduling
- **Cost-effective**: ~$35 device vs cloud hosting
- **Local control**: No external dependencies
- **Sufficient specs**: 1GB RAM, quad-core CPU handles WhatsApp automation well

### Hardware Requirements

- Raspberry Pi 3 Model B+ (1GB RAM)
- MicroSD card (16GB minimum, 32GB recommended, Class 10)
- Power supply (5V 2.5A minimum, official adapter recommended)
- Ethernet cable (recommended for stability) or WiFi
- Case with heatsinks (recommended for 24/7 operation)

### Step 1: Prepare the OS

**1.1 Download Raspberry Pi OS Lite (64-bit)**
- Visit https://www.raspberrypi.com/software/
- Download "Raspberry Pi OS Lite (64-bit)" - headless, no desktop
- Or use Raspberry Pi Imager tool

**1.2 Flash to microSD card**
```bash
# On your computer (Linux/Mac)
# Find your SD card device
lsblk

# Flash the image (replace /dev/sdX with your SD card)
sudo dd if=2024-11-19-raspios-bookworm-arm64-lite.img of=/dev/sdX bs=4M status=progress
sync
```

**1.3 Enable SSH (headless setup)**
```bash
# Mount the boot partition
cd /media/$USER/bootfs  # or wherever it mounted

# Create empty ssh file to enable SSH
touch ssh
```

**1.4 Configure WiFi (optional, if not using Ethernet)**
```bash
# Create wpa_supplicant.conf in boot partition
nano wpa_supplicant.conf
```

Add:
```
country=NL
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1

network={
    ssid="YourWiFiName"
    psk="YourWiFiPassword"
}
```

**1.5 Boot the Pi**
- Insert SD card into Pi
- Connect Ethernet (or rely on WiFi)
- Connect power
- Wait 60 seconds for boot

**1.6 Find Pi's IP address**
```bash
# On your computer
nmap -sn 192.168.1.0/24  # Adjust to your subnet
# Or check your router's DHCP leases
```

**1.7 SSH into Pi**
```bash
ssh pi@192.168.1.XXX
# Default password: raspberry
```

**1.8 Change default password**
```bash
passwd
# Set a strong password
```

**1.9 Update system**
```bash
sudo apt update && sudo apt upgrade -y
sudo reboot
```

### Step 2: Install Dependencies

**2.1 Reconnect after reboot**
```bash
ssh pi@192.168.1.XXX
```

**2.2 Install Node.js 18.x**
```bash
# Add NodeSource repository
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -

# Install Node.js
sudo apt install -y nodejs

# Verify
node --version  # Should show v18.x.x
npm --version
```

**2.3 Install Python 3 and pip (usually pre-installed)**
```bash
sudo apt install -y python3 python3-pip python3-venv

# Verify
python3 --version  # Should show 3.9 or higher
```

**2.4 Install Chromium browser**
```bash
sudo apt install -y chromium-browser chromium-chromedriver

# Verify installation
chromium-browser --version
which chromium-browser  # Should show /usr/bin/chromium-browser
```

**2.5 Install system dependencies**
```bash
# Required for Puppeteer and open-wa
sudo apt install -y \
  gconf-service \
  libasound2 \
  libatk1.0-0 \
  libc6 \
  libcairo2 \
  libcups2 \
  libdbus-1-3 \
  libexpat1 \
  libfontconfig1 \
  libgcc1 \
  libgconf-2-4 \
  libgdk-pixbuf2.0-0 \
  libglib2.0-0 \
  libgtk-3-0 \
  libnspr4 \
  libpango-1.0-0 \
  libpangocairo-1.0-0 \
  libstdc++6 \
  libx11-6 \
  libx11-xcb1 \
  libxcb1 \
  libxcomposite1 \
  libxcursor1 \
  libxdamage1 \
  libxext6 \
  libxfixes3 \
  libxi6 \
  libxrandr2 \
  libxrender1 \
  libxss1 \
  libxtst6 \
  ca-certificates \
  fonts-liberation \
  libappindicator1 \
  libnss3 \
  lsb-release \
  xdg-utils \
  wget
```

### Step 3: Install WhatsApp Scheduler

**3.1 Create project directory**
```bash
mkdir -p ~/whatsapp_scheduler
cd ~/whatsapp_scheduler
```

**3.2 Transfer files to Pi**

Option A: Git clone (if repository available)
```bash
git clone <your-repo-url> .
```

Option B: SCP from your computer
```bash
# On your computer, in the project directory
scp -r * pi@192.168.1.XXX:~/whatsapp_scheduler/
```

Option C: Manual file creation (copy files one by one using nano)

**3.3 Install Node.js dependencies**
```bash
cd ~/whatsapp_scheduler
npm install
```

**3.4 Create Python virtual environment**
```bash
python3 -m venv venv
source venv/bin/activate
```

**3.5 Install Python dependencies**
```bash
pip install -r requirements.txt
```

**3.6 Create required directories**
```bash
mkdir -p schedules logs
chmod +x start_all.sh stop_all.sh setup_logs.sh
./setup_logs.sh
```

### Step 4: Configure and Test

**4.1 Configure Chromium path in server.js**

The default should work, but verify:
```bash
nano server.js
```

Look for this section and ensure it matches:
```javascript
create({
  sessionId: 'whatsapp_scheduler',
  multiDevice: false,
  useChrome: true,
  executablePath: '/usr/bin/chromium-browser',  // Verify this path
  chromiumArgs: [
    '--no-sandbox',
    '--disable-setuid-sandbox',
    '--disable-dev-shm-usage',
    '--disable-accelerated-2d-canvas',
    '--no-first-run',
    '--no-zygote',
    '--disable-gpu'
  ],
  // ... rest of config
})
```

**4.2 First authentication**
```bash
cd ~/whatsapp_scheduler
node server.js
```

- QR code will appear in terminal
- Open WhatsApp on your phone
- Go to Settings → Linked Devices → Link a Device
- Scan the QR code
- Wait for "WhatsApp client ready!"
- Press Ctrl+C to stop

Session is now saved to `whatsapp_scheduler.data.json`.

**4.3 Test the system**
```bash
# Start driver in background
node server.js &

# Wait 30 seconds for driver to initialize
sleep 30

# Check driver status
curl http://localhost:5001/status

# Start background scheduler (in another terminal or screen)
source venv/bin/activate
python3 background_scheduler.py &

# Start Flask UI (optional, for web interface)
python3 app.py &

# Check if all running
ps aux | grep -E 'node|python.*background|python.*app'
```

**4.4 Test from another device on your network**
- Find Pi's IP: `hostname -I`
- Visit `http://192.168.1.XXX:5000` in browser
- Add a test schedule
- Check if it sends

**4.5 Stop test processes**
```bash
./stop_all.sh
# Or manually:
killall node
killall python3
```

### Step 5: Configure Autostart with Systemd

**5.1 Create systemd service for driver**
```bash
sudo nano /etc/systemd/system/whatsapp-driver.service
```

Add:
```ini
[Unit]
Description=WhatsApp Driver (open-wa)
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/whatsapp_scheduler
ExecStart=/usr/bin/node server.js
Restart=always
RestartSec=10
StandardOutput=append:/home/pi/whatsapp_scheduler/logs/driver.log
StandardError=append:/home/pi/whatsapp_scheduler/logs/driver.log

[Install]
WantedBy=multi-user.target
```

**5.2 Create systemd service for scheduler**
```bash
sudo nano /etc/systemd/system/whatsapp-scheduler.service
```

Add:
```ini
[Unit]
Description=WhatsApp Background Scheduler
After=network.target whatsapp-driver.service
Requires=whatsapp-driver.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/whatsapp_scheduler
ExecStart=/home/pi/whatsapp_scheduler/venv/bin/python3 background_scheduler.py
Restart=always
RestartSec=10
StandardOutput=append:/home/pi/whatsapp_scheduler/logs/scheduler.log
StandardError=append:/home/pi/whatsapp_scheduler/logs/scheduler.log

[Install]
WantedBy=multi-user.target
```

**5.3 Create systemd service for Flask (optional)**
```bash
sudo nano /etc/systemd/system/whatsapp-flask.service
```

Add:
```ini
[Unit]
Description=WhatsApp Scheduler Flask UI
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/whatsapp_scheduler
ExecStart=/home/pi/whatsapp_scheduler/venv/bin/python3 app.py
Restart=always
RestartSec=10
StandardOutput=append:/home/pi/whatsapp_scheduler/logs/flask.log
StandardError=append:/home/pi/whatsapp_scheduler/logs/flask.log

[Install]
WantedBy=multi-user.target
```

**5.4 Enable and start services**
```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable services (start on boot)
sudo systemctl enable whatsapp-driver
sudo systemctl enable whatsapp-scheduler
sudo systemctl enable whatsapp-flask  # optional

# Start services now
sudo systemctl start whatsapp-driver
sleep 30  # Wait for driver to initialize
sudo systemctl start whatsapp-scheduler
sudo systemctl start whatsapp-flask  # optional
```

**5.5 Check service status**
```bash
sudo systemctl status whatsapp-driver
sudo systemctl status whatsapp-scheduler
sudo systemctl status whatsapp-flask
```

**5.6 View logs**
```bash
# Real-time logs
sudo journalctl -u whatsapp-driver -f
sudo journalctl -u whatsapp-scheduler -f
sudo journalctl -u whatsapp-flask -f

# Or view log files directly
tail -f ~/whatsapp_scheduler/logs/driver.log
tail -f ~/whatsapp_scheduler/logs/scheduler.log
tail -f ~/whatsapp_scheduler/logs/flask.log
```

### Step 6: Security and Optimization

**6.1 Configure firewall**
```bash
# Install ufw
sudo apt install -y ufw

# Allow SSH
sudo ufw allow 22/tcp

# Allow Flask UI only from local network
sudo ufw allow from 192.168.1.0/24 to any port 5000

# Enable firewall
sudo ufw enable
sudo ufw status
```

**6.2 Setup log rotation**
```bash
sudo nano /etc/logrotate.d/whatsapp-scheduler
```

Add:
```
/home/pi/whatsapp_scheduler/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 644 pi pi
}
```

**6.3 Monitor system resources**
```bash
# Install htop
sudo apt install -y htop

# Monitor
htop

# Check memory usage
free -h

# Check disk usage
df -h
```

**6.4 Optimize for 24/7 operation**
```bash
# Reduce SD card writes (add to /etc/fstab)
sudo nano /etc/fstab
```

Add these lines:
```
tmpfs /tmp tmpfs defaults,noatime,nosuid,size=100m 0 0
tmpfs /var/tmp tmpfs defaults,noatime,nosuid,size=30m 0 0
tmpfs /var/log tmpfs defaults,noatime,nosuid,mode=0755,size=100m 0 0
```

Apply:
```bash
sudo mount -a
```

**6.5 Setup automatic updates (optional)**
```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

### Step 7: Maintenance and Troubleshooting

**Common Issues:**

**Issue: Driver won't start**
```bash
# Check Chromium path
which chromium-browser

# Check logs
sudo journalctl -u whatsapp-driver -n 100

# Test manually
cd ~/whatsapp_scheduler
node server.js
```

**Issue: QR code won't appear on headless Pi**
```bash
# The QR should still print to console/logs
sudo journalctl -u whatsapp-driver -n 100 | grep -A 20 "qr"

# Or check driver.log
cat ~/whatsapp_scheduler/logs/driver.log | grep -A 20 "qr"
```

**Issue: Schedules not sending**
```bash
# Check if scheduler is running
sudo systemctl status whatsapp-scheduler

# Check driver is ready
curl http://localhost:5001/status

# Check schedule file
cat ~/whatsapp_scheduler/schedules/schedule.json | python3 -m json.tool

# Check logs
tail -f ~/whatsapp_scheduler/logs/scheduler.log
```

**Issue: High memory usage**
```bash
# Check current usage
free -h

# Restart services
sudo systemctl restart whatsapp-driver
sudo systemctl restart whatsapp-scheduler

# If persistent, consider adding swap
sudo dphys-swapfile swapoff
sudo nano /etc/dphys-swapfile
# Change CONF_SWAPSIZE=100 to CONF_SWAPSIZE=1024
sudo dphys-swapfile setup
sudo dphys-swapfile swapon
```

**Issue: Pi becomes unresponsive**
```bash
# Check for overheating
vcgencmd measure_temp

# If > 80°C, add heatsinks or improve ventilation
# Consider throttling Chromium:
nano ~/whatsapp_scheduler/server.js
# Add to chromiumArgs: '--disable-features=VizDisplayCompositor'
```

**Useful Commands:**

```bash
# Restart all services
sudo systemctl restart whatsapp-driver whatsapp-scheduler whatsapp-flask

# Stop all services
sudo systemctl stop whatsapp-driver whatsapp-scheduler whatsapp-flask

# View service logs since last boot
sudo journalctl -u whatsapp-driver -b

# Check system temperature
vcgencmd measure_temp

# Check CPU frequency (throttling detection)
vcgencmd measure_clock arm

# Network connectivity test
ping -c 4 8.8.8.8

# Check if ports are listening
sudo netstat -tulpn | grep -E '5000|5001'
```

**Backup and Restore:**

```bash
# Backup configuration and session
cd ~/whatsapp_scheduler
tar -czf backup_$(date +%Y%m%d).tar.gz \
  whatsapp_scheduler.data.json \
  schedules/ \
  _IGNORE_whatsapp_scheduler/

# Restore
tar -xzf backup_20250115.tar.gz
sudo systemctl restart whatsapp-driver whatsapp-scheduler
```

**Remote Access:**

Setup SSH key authentication for secure remote access:
```bash
# On your computer
ssh-keygen -t ed25519
ssh-copy-id pi@192.168.1.XXX

# Now you can SSH without password
ssh pi@192.168.1.XXX
```

Access Flask UI from anywhere (use with caution):
```bash
# Setup reverse SSH tunnel from external server
ssh -R 8080:localhost:5000 user@your-external-server.com

# Or use ngrok (temporary public URL)
# Install ngrok on Pi, then:
ngrok http 5000
```

### Performance Tips for Raspberry Pi 3B+

1. **Use Ethernet instead of WiFi** - more stable connection
2. **Use high-quality SD card** - Class 10 or UHS-I for better I/O
3. **Disable unused services** - `sudo systemctl disable bluetooth`
4. **Use Lite OS** - no desktop environment saves ~300MB RAM
5. **Monitor temperature** - ensure proper cooling for 24/7 operation
6. **Regular reboots** - schedule weekly reboot: `sudo crontab -e` → `0 3 * * 0 /sbin/shutdown -r now`
7. **Limit concurrent operations** - don't run heavy tasks during schedule checks
8. **Use background scheduler only** - Flask UI not needed for operation

### Expected Performance

On Raspberry Pi 3B+:
- **Boot time**: ~45 seconds to system ready
- **Driver initialization**: 20-40 seconds for WhatsApp connection
- **Memory usage**: ~400-600MB (driver ~300MB, scheduler ~50MB, Flask ~80MB)
- **CPU usage**: <5% idle, 20-40% during message send
- **Reliability**: 99%+ uptime with systemd auto-restart
- **Schedule accuracy**: ±10 seconds (10-second check interval)

---

**You now have a fully operational WhatsApp Scheduler on Raspberry Pi 3B+!**

Access the web interface at: `http://your-pi-ip:5000`

For questions or issues, check the troubleshooting section or review logs.

## License

See LICENSE file for details.

## Further work:
V2 can upgrade to use Baileys lighter weight websocket connection to WhatsApp instead of open-wa running a headless chromium whatsapp web. This will be a lot lighter weight and faster. 
