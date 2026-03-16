#!/bin/bash
# Fresh start - clear ALL WhatsApp session data and restart services
#
# ⚠️  WARNING: This script DELETES all session data!
# You will need to re-scan the QR code after running this.
#
# Use this script ONLY when:
# - QR code is not being generated (session data exists but is invalid)
# - You want to re-authenticate with a different WhatsApp account
# - Session is corrupted or authentication is stuck
#
# For routine maintenance (memory clean-up), use daily_maintenance.sh
# instead — that script preserves session data.

echo "=== Fresh Start - Clearing WhatsApp Session ==="
echo ""
echo "⚠️  WARNING: This will delete all session data!"
echo "   You will need to re-scan the QR code after this."
echo ""
read -p "Are you sure? (y/N) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi
echo ""

# Stop all running services first
echo "Stopping all services..."

# Try to stop systemd services (if they exist and are active)
if systemctl is-active --quiet whatsapp-driver.service 2>/dev/null; then
    echo "Stopping systemd services (timeout 10s)..."
    sudo timeout 10 systemctl stop whatsapp-flask.service 2>/dev/null || true
    sudo timeout 10 systemctl stop whatsapp-scheduler.service 2>/dev/null || true
    sudo timeout 10 systemctl stop whatsapp-driver.service 2>/dev/null || true
    sudo timeout 10 systemctl stop whatsapp-maintenance.service 2>/dev/null || true
    sudo timeout 10 systemctl stop whatsapp-maintenance.timer 2>/dev/null || true

    # If still running, force kill
    if systemctl is-active --quiet whatsapp-driver.service 2>/dev/null; then
        echo "Force killing driver service..."
        sudo systemctl kill whatsapp-driver.service 2>/dev/null || true
    fi
fi

# Kill any manually started processes and Chromium
pkill -f "node server.js" 2>/dev/null || true
pkill -f "background_scheduler.py" 2>/dev/null || true
pkill -f "app.py" 2>/dev/null || true
pkill -f chromium 2>/dev/null || true
sleep 2

# Remove open-wa session data files
echo "Clearing open-wa session data files..."
rm -f whatsapp_scheduler.data.json
rm -f whatsapp_scheduler_MULTI_DEVICE.data.json
rm -f qr_code.png
rm -f qr_screenshot.png
echo "  ✓ Session data JSON files removed"

# Remove browser profile (contains cookies, local storage, auth tokens)
echo "Clearing browser session store..."
if [ -d "whatsapp_session_store" ]; then
    rm -rf whatsapp_session_store/
    echo "  ✓ Browser session store cleared"
else
    echo "  (no browser session store found)"
fi

# Also remove legacy session directories if they exist
if [ -d "_IGNORE_whatsapp_scheduler" ]; then
    rm -rf _IGNORE_whatsapp_scheduler/
    echo "  ✓ Legacy session directory cleared"
fi

echo ""
echo "✅ Fresh start complete!"
echo ""
echo "Next steps:"
echo "  1. Run: node server.js   (or start via systemd)"
echo "  2. Open: http://<pi-ip>:5001/qr_code.png"
echo "  3. Scan the QR code with your phone"
echo "  4. WAIT at least 5 minutes before stopping the server"
echo "     (this ensures session data is fully saved)"
