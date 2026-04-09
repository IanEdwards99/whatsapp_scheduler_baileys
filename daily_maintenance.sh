#!/bin/bash
# Daily maintenance script for WhatsApp Scheduler
#
# PURPOSE: Check system health and ONLY restart if needed.
# Avoids unnecessary restarts that risk timeout/auth failures on the Pi.
#
# STRATEGY:
#   1. Check free memory — if below threshold, restart to reclaim leaked RAM
#   2. Check driver health — if unresponsive, restart
#   3. If everything is healthy, just log and exit (NO restart)
#
# IMPORTANT: This script NEVER deletes session data!
#   - baileys_auth_info/  (Baileys session data)
# Deleting these would force a QR re-scan, which is not desirable for a
# headless deployment.
#
# Installation:
#   chmod +x daily_maintenance.sh
#   sudo crontab -e
#   Add: 0 4 * * * /home/iedwards/development/whatsapp_driver_baileys/daily_maintenance.sh

LOG_FILE="/home/iedwards/development/whatsapp_driver_baileys/logs/maintenance.log"
PROJECT_DIR="/home/iedwards/development/whatsapp_driver_baileys"

# Threshold: restart if free memory drops below this (in MB)
# Pi has ~1024MB total. Chromium needs ~300-400MB to restart safely.
# If free < 150MB, we're at risk of OOM during normal operation.
MEM_THRESHOLD_MB=150

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

echo "$(date '+%Y-%m-%d %H:%M:%S') - === Daily maintenance check ===" >> "$LOG_FILE"

# ─────────────────────────────────────────────────
# 1. Gather system info
# ─────────────────────────────────────────────────
FREE_MEM=$(free -m | awk '/^Mem:/{print $7}')   # "available" is more accurate than "free"
TOTAL_MEM=$(free -m | awk '/^Mem:/{print $2}')
echo "$(date '+%Y-%m-%d %H:%M:%S') - Memory: ${FREE_MEM}MB available / ${TOTAL_MEM}MB total" >> "$LOG_FILE"

# 2. Check driver health via /status endpoint
DRIVER_SYSTEMD_OK=false
DRIVER_API_OK=false
NEEDS_RESTART=false
RESTART_REASON=""

if systemctl is-active --quiet whatsapp-driver; then
    DRIVER_SYSTEMD_OK=true
    # Check if the API is actually responding and the client is ready
    STATUS=$(curl -s --max-time 10 http://localhost:5001/status 2>/dev/null || echo '{}')
    READY=$(echo "$STATUS" | grep -o '"ready":true' || true)
    if [ -n "$READY" ]; then
        DRIVER_API_OK=true
    fi
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') - Driver systemd: $([ "$DRIVER_SYSTEMD_OK" = true ] && echo 'active' || echo 'INACTIVE')" >> "$LOG_FILE"
echo "$(date '+%Y-%m-%d %H:%M:%S') - Driver API ready: $([ "$DRIVER_API_OK" = true ] && echo 'yes' || echo 'NO')" >> "$LOG_FILE"

# ─────────────────────────────────────────────────
# 3. Decide whether to restart
# ─────────────────────────────────────────────────

# Reason 1: Driver is down or unresponsive
if [ "$DRIVER_SYSTEMD_OK" = false ]; then
    NEEDS_RESTART=true
    RESTART_REASON="Driver systemd service is not running"
elif [ "$DRIVER_API_OK" = false ]; then
    NEEDS_RESTART=true
    RESTART_REASON="Driver API is not responding or client not ready"
fi

# Reason 2: Memory is critically low (Memory leak)
if [ "$FREE_MEM" -lt "$MEM_THRESHOLD_MB" ] 2>/dev/null; then
    NEEDS_RESTART=true
    RESTART_REASON="${RESTART_REASON:+$RESTART_REASON; }Low memory (${FREE_MEM}MB < ${MEM_THRESHOLD_MB}MB threshold)"
fi

# ─────────────────────────────────────────────────
# 4. Act on decision
# ─────────────────────────────────────────────────
if [ "$NEEDS_RESTART" = false ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - ✅ System healthy. No restart needed." >> "$LOG_FILE"
    echo "---" >> "$LOG_FILE"
    exit 0
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') - ⚠️  RESTART NEEDED: ${RESTART_REASON}" >> "$LOG_FILE"

# ─────────────────────────────────────────────────
# 5. Perform restart
# ─────────────────────────────────────────────────

# 5a. Stop services (scheduler first, then driver)
echo "$(date '+%Y-%m-%d %H:%M:%S') - Stopping whatsapp-scheduler service..." >> "$LOG_FILE"
sudo systemctl stop whatsapp-scheduler
echo "$(date '+%Y-%m-%d %H:%M:%S') - Stopping whatsapp-driver service..." >> "$LOG_FILE"
sudo systemctl stop whatsapp-driver

# Wait for process to fully exit
echo "Waiting for graceful shutdown..." >> "$LOG_FILE"
sleep 15

# 5b. Check for zombie processes and kill if necessary
if pgrep -f "chromium" > /dev/null; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Cleaning up stuck Chromium processes..." >> "$LOG_FILE"
    pkill -f "chromium"
    sleep 2
fi

if pgrep -f "server.js" > /dev/null; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Cleaning up stuck Node processes..." >> "$LOG_FILE"
    pkill -f "server.js"
    sleep 2
fi

# 5c. Clean up temp files (never session data!)
rm -f "${PROJECT_DIR}/qr_screenshot.png" 2>/dev/null

# 5d. Drop filesystem caches to maximize available memory
echo "$(date '+%Y-%m-%d %H:%M:%S') - Dropping filesystem caches..." >> "$LOG_FILE"
sync
echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true
sleep 2

FREE_MEM_POST_CACHE=$(free -m | awk '/^Mem:/{print $7}')
echo "$(date '+%Y-%m-%d %H:%M:%S') - Free memory after cache drop: ${FREE_MEM_POST_CACHE}MB" >> "$LOG_FILE"

# ─────────────────────────────────────────────────
# 6. Start driver and wait for readiness
# ─────────────────────────────────────────────────
echo "$(date '+%Y-%m-%d %H:%M:%S') - Starting whatsapp-driver service..." >> "$LOG_FILE"
sudo systemctl start whatsapp-driver

# Smart polling: check /status endpoint every 30s for up to 20 minutes.
# The driver has its own internal retry logic (3 attempts with backoff).
MAX_WAIT=1200
POLL_INTERVAL=30
ELAPSED=0
DRIVER_READY=false

echo "$(date '+%Y-%m-%d %H:%M:%S') - Waiting for driver to become ready (max ${MAX_WAIT}s)..." >> "$LOG_FILE"

while [ "$ELAPSED" -lt "$MAX_WAIT" ]; do
    sleep "$POLL_INTERVAL"
    ELAPSED=$((ELAPSED + POLL_INTERVAL))

    if ! systemctl is-active --quiet whatsapp-driver; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - Driver service stopped unexpectedly after ${ELAPSED}s" >> "$LOG_FILE"
        break
    fi

    STATUS=$(curl -s --max-time 5 http://localhost:5001/status 2>/dev/null || echo '{}')
    READY=$(echo "$STATUS" | grep -o '"ready":true' || true)

    if [ -n "$READY" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - Driver is READY after ${ELAPSED}s" >> "$LOG_FILE"
        DRIVER_READY=true
        break
    fi

    echo "$(date '+%Y-%m-%d %H:%M:%S') - Still waiting... (${ELAPSED}s elapsed)" >> "$LOG_FILE"
done

# ─────────────────────────────────────────────────
# 7. Start scheduler
# ─────────────────────────────────────────────────
if [ "$DRIVER_READY" = true ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Starting whatsapp-scheduler service..." >> "$LOG_FILE"
    sudo systemctl start whatsapp-scheduler
    sleep 5

    if systemctl is-active --quiet whatsapp-scheduler; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - ✅ Scheduler started successfully" >> "$LOG_FILE"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') - ERROR: Scheduler failed to start" >> "$LOG_FILE"
    fi
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') - CRITICAL: Driver never became ready after ${MAX_WAIT}s" >> "$LOG_FILE"
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Leaving driver running (systemd Restart=always will handle recovery)" >> "$LOG_FILE"
fi

# ─────────────────────────────────────────────────
# 8. Final status
# ─────────────────────────────────────────────────
FREE_MEM_AFTER=$(free -m | awk '/^Mem:/{print $7}')
echo "$(date '+%Y-%m-%d %H:%M:%S') - Memory after maintenance: ${FREE_MEM_AFTER}MB (was ${FREE_MEM}MB)" >> "$LOG_FILE"
echo "$(date '+%Y-%m-%d %H:%M:%S') - Daily maintenance complete" >> "$LOG_FILE"
echo "---" >> "$LOG_FILE"
