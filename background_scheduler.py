#!/usr/bin/env python3
"""
Background Scheduler for WhatsApp Messages and Polls

This standalone process runs independently of Flask and continuously monitors
the schedule file for pending messages/polls to send.

Architecture:
- Runs in infinite loop with configurable check interval (default 10 seconds)
- Reads schedules from schedules/schedule.json with file locking
- Sends via driver HTTP API (port 5002)
- Logs all sends to message_history.json
- Updates recurring schedules automatically

Key Features:
- Status tracking: only processes schedules with status='pending'
- Recurring support: auto-updates next_run for daily/weekly/monthly
- History logging: tracks every send with metadata
- Error recovery: marks failed sends, continues processing
- Driver health check: verifies driver ready before sending
- Auto-restart: restarts driver service after consecutive failures
- Email alerts: notifies on failures and restarts

Usage:
    python3 background_scheduler.py
    
Or as systemd service for production deployment.
"""

import time
import requests
import logging
import threading
import subprocess
import os
from datetime import datetime
from dotenv import load_dotenv
from scheduler_core import MessageScheduler
from message_history import MessageHistory
from email_notifications import get_notifier

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
SCHEDULE_FILE = "schedules/schedule.json"
DRIVER_SERVER_URL = os.environ.get("DRIVER_URL", "http://127.0.0.1:5002")
CHECK_INTERVAL = 30  # Check every 30 seconds for pending schedules (reduced for Pi)
MAX_CONSECUTIVE_FAILURES = 20  # Restart driver after ~10 minutes of failures
DRIVER_RESTART_COOLDOWN = 900  # Wait 15 minutes between restart attempts


class EnhancedScheduleProcessor:
    """
    Processes scheduled messages and polls with full tracking
    
    This class orchestrates the entire scheduling workflow:
    1. Check driver health
    2. Load pending schedules
    3. Send via driver API
    4. Log to message history
    5. Update schedule status (mark completed or failed)
    6. Calculate next run time for recurring schedules
    """
    
    def __init__(self, schedule_file: str, driver_url: str):
        """
        Initialize processor with schedule file and driver URL
        
        Args:
            schedule_file: Path to schedule.json
            driver_url: Base URL for driver API (e.g., http://127.0.0.1:5002)
        """
        self.scheduler = MessageScheduler(schedule_file)
        self.driver_url = driver_url
        self.history = MessageHistory()  # Message history tracker
        self.consecutive_failures = 0  # Track failures for auto-restart
        self.last_restart_time = 0  # Track last restart to avoid restart loops
    
    def restart_driver(self) -> bool:
        """
        Attempt to restart the WhatsApp driver service via systemctl
        
        Returns:
            bool: True if restart command succeeded, False otherwise
        """
        current_time = time.time()
        
        # Check cooldown period
        if current_time - self.last_restart_time < DRIVER_RESTART_COOLDOWN:
            remaining = int(DRIVER_RESTART_COOLDOWN - (current_time - self.last_restart_time))
            logger.warning(f"Driver restart cooldown active ({remaining}s remaining)")
            return False
        
        logger.warning("⚠️ Attempting to restart whatsapp-driver service...")
        
        # Send email notification about restart
        get_notifier().send_driver_restart_alert(
            f"{self.consecutive_failures} consecutive failures detected"
        )
        
        try:
            # Use systemctl to restart the driver
            result = subprocess.run(
                ['sudo', 'systemctl', 'restart', 'whatsapp-driver'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                logger.info("✓ Driver service restart initiated")
                self.last_restart_time = current_time
                self.consecutive_failures = 0
                
                # Wait for driver to come back up
                logger.info("Waiting 60 seconds for driver to initialize...")
                time.sleep(60)
                return True
            else:
                logger.error(f"✗ Failed to restart driver: {result.stderr}")
                get_notifier().send_critical_error_alert(f"Failed to restart driver: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("✗ Driver restart command timed out")
            get_notifier().send_critical_error_alert("Driver restart command timed out")
            return False
        except Exception as e:
            logger.error(f"✗ Error restarting driver: {e}")
            get_notifier().send_critical_error_alert(f"Error restarting driver: {e}")
            return False
    
    def check_driver_ready(self) -> bool:
        """
        Check if WhatsApp driver is ready to send messages
        
        Calls driver /status endpoint to verify:
        - Server is running
        - WhatsApp client is initialized
        - Session is authenticated
        
        Tracks consecutive failures and triggers auto-restart if needed.
        
        Returns:
            bool: True if driver is ready, False otherwise
        """
        try:
            # Increase timeout for Pi (slow response during heavy load)
            response = requests.get(f"{self.driver_url}/status", timeout=30)
            if response.status_code == 200:
                data = response.json()
                ready = data.get('ready', False)
                if ready:
                    # Reset failure counter on success
                    if self.consecutive_failures > 0:
                        logger.info(f"Driver recovered after {self.consecutive_failures} failures")
                    self.consecutive_failures = 0
                    return True
                else:
                    logger.warning("Driver running but WhatsApp client not ready (may need re-authentication)")
                    return False
        except requests.Timeout:
            logger.warning("Driver health check timed out - driver may be overloaded or crashed")
        except requests.ConnectionError:
            logger.warning("Cannot connect to driver - service may be down")
        except requests.RequestException as e:
            logger.debug(f"Driver health check failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in health check: {e}")
        
        # Track failure and potentially restart
        self.consecutive_failures += 1
        logger.warning(f"Driver failure count: {self.consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}")
        
        if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            logger.error(f"⚠️ {MAX_CONSECUTIVE_FAILURES} consecutive driver failures - triggering restart")
            self.restart_driver()
        
        return False
    
    def process_schedules(self):
        """
        Process all pending schedules
        
        Workflow:
        1. Verify driver is ready
        2. Get pending schedules (status='pending', time reached)
        3. Send each schedule via driver API
        4. Log send result to message history
        5. Mark schedule as completed or failed
        6. For recurring: calculate next run time and reset status to pending
        """
        if not self.check_driver_ready():
            logger.warning("Driver not ready - skipping this check cycle")
            return
        
        # Get all schedules that are pending and due for sending
        pending = self.scheduler.get_pending_schedules()
        
        if not pending:
            logger.debug("No pending schedules")
            return
        
        logger.info(f"Processing {len(pending)} pending schedule(s)")
        
        for idx, schedule in pending:
            try:
                # Send the schedule and get success status
                success = self._send_schedule(schedule)
                
                # Update schedule status (also handles recurring logic)
                self.scheduler.mark_completed(idx, success)
                
                if success:
                    logger.info(f"✓ Completed: {schedule['contact']} ({schedule['type']})")
                else:
                    logger.error(f"✗ Failed: {schedule['contact']} ({schedule['type']})")
                
            except Exception as e:
                logger.error(f"Error processing schedule: {e}", exc_info=True)
                # Mark as failed so we don't retry immediately
                self.scheduler.mark_completed(idx, False)
    
    def _send_schedule(self, schedule: dict) -> bool:
        """
        Send a single schedule via driver API and log to history
        
        Handles both message and poll types with appropriate API calls.
        Logs detailed metadata including scheduled time, recurring type, etc.
        
        Args:
            schedule: Schedule dict containing type, contact, message/question, etc.
            
        Returns:
            bool: True if send successful, False otherwise
        """
        sched_type = schedule.get('type')
        contact = schedule.get('contact')
        
        try:
            # Handle MESSAGE type
            if sched_type == 'message':
                message = schedule.get('message')
                logger.info(f"Sending message to {contact}: {message[:50]}...")
                
                # Send via driver API
                success, error_detail = self.scheduler.send_message_via_api(contact, message)
                
                # Send email alert on failure
                if not success:
                    get_notifier().send_failure_alert(
                        contact=contact,
                        content_type='message',
                        error=f"Failed to send message: {error_detail or message[:100]}"
                    )
                
                # Log to message history with metadata
                self.history.add_entry(
                    entry_type='message',
                    contact=contact,
                    content={'message': message},
                    status='sent' if success else 'failed',
                    metadata={
                        'source': 'scheduled',
                        'recurring': schedule.get('recurring'),
                        'scheduled_time': schedule.get('time'),
                        **(({'error': error_detail} if error_detail else {}))
                    }
                )
                
                return success
            
            # Handle POLL type
            elif sched_type == 'poll':
                question = schedule.get('question')
                options = schedule.get('options', [])
                allow_multi_select = schedule.get('allow_multi_select', False)
                logger.info(f"Sending poll to {contact}: {question[:50]}...")
                
                # Send via driver API
                success, error_detail = self.scheduler.send_poll_via_api(contact, question, options, allow_multi_select)
                
                # Send email alert on failure
                if not success:
                    get_notifier().send_failure_alert(
                        contact=contact,
                        content_type='poll',
                        error=f"Failed to send poll: {error_detail or question}"
                    )
                
                # Log to message history with metadata
                self.history.add_entry(
                    entry_type='poll',
                    contact=contact,
                    content={'question': question, 'options': options, 'allow_multi_select': allow_multi_select},
                    status='sent' if success else 'failed',
                    metadata={
                        'source': 'scheduled',
                        'recurring': schedule.get('recurring'),
                        'scheduled_time': schedule.get('time'),
                        **(({'error': error_detail} if error_detail else {}))
                    }
                )
                
                return success
            
            else:
                logger.error(f"Unknown schedule type: {sched_type}")
                return False
                
        except Exception as e:
            logger.error(f"Error sending schedule: {e}", exc_info=True)
            
            # Log error to history
            self.history.add_entry(
                entry_type=sched_type or 'unknown',
                contact=contact or 'unknown',
                content={'error': str(e)},
                status='error',
                metadata={'source': 'scheduled'}
            )
            
            return False
    
    def run(self):
        """
        Main scheduler loop
        
        Runs indefinitely, checking for pending schedules every CHECK_INTERVAL seconds.
        Handles graceful shutdown on Ctrl+C or SIGTERM.
        
        Process:
        1. Check pending schedules
        2. Send any that are due
        3. Sleep for CHECK_INTERVAL
        4. Repeat
        
        This can be run as:
        - Foreground process (python3 background_scheduler.py)
        - Background process (python3 background_scheduler.py &)
        - Systemd service (see README for systemd setup)
        """
        logger.info("=" * 60)
        logger.info("WhatsApp Background Scheduler Starting")
        logger.info("=" * 60)
        logger.info(f"Check interval: {CHECK_INTERVAL} seconds")
        logger.info(f"Schedule file: {self.scheduler.schedule_file}")
        logger.info(f"Driver URL: {self.driver_url}")
        logger.info(f"History file: schedules/message_history.json")
        logger.info("=" * 60)
        
        try:
            while True:
                self.process_schedules()
                time.sleep(CHECK_INTERVAL)
        
        except KeyboardInterrupt:
            logger.info("\nScheduler stopped by user (Ctrl+C)")
        except Exception as e:
            logger.error(f"Scheduler fatal error: {e}", exc_info=True)
            raise


if __name__ == "__main__":
    # Start Telegram bot in background thread if available
    try:
        from telegram_bot import run_bot
        telegram_thread = threading.Thread(target=run_bot, daemon=True)
        telegram_thread.start()
        logger.info("Started Telegram bot in background thread")
    except Exception as e:
        logger.error(f"Failed to start telegram bot: {e}")

    # Create processor and start main loop
    processor = EnhancedScheduleProcessor(SCHEDULE_FILE, DRIVER_SERVER_URL)
    processor.run()

