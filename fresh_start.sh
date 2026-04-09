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

# Kill any manually started processes
pkill -f "node server.js" 2>/dev/null || true
pkill -f "background_scheduler.py" 2>/dev/null || true
pkill -f "app.py" 2>/dev/null || true
sleep 2

# Remove generated QR file
rm -f qr_code.png
echo "  ✓ QR code file removed"

# Remove Baileys auth session (contains credentials)
echo "Clearing Baileys auth session..."
if [ -d "baileys_auth_info" ]; then
    rm -rf baileys_auth_info/
    echo "  ✓ Baileys auth session cleared"
else
    echo "  (no baileys_auth_info directory found)"
fi

echo ""
echo "✅ Fresh start complete!"
echo ""
echo "Next steps:"
echo "  1. Run: node server.js   (or start via systemd)"
echo "  2. Open: http://<pi-ip>:5001/qr_code.png"
echo "  3. Scan the QR code with your phone"
echo "  4. WAIT for 'Opened connection, fully authenticated!' in the logs"
