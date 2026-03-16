#!/usr/bin/env python3
"""
Email Notification Service for WhatsApp Scheduler

Sends email alerts when:
- Driver fails to send a message
- Driver becomes unresponsive
- Driver is restarted
- Any critical errors occur

Configuration:
    Set environment variables or edit the config below:
    - EMAIL_SENDER: Your Gmail address
    - EMAIL_PASSWORD: Gmail App Password (not regular password)
    - EMAIL_RECIPIENT: Where to send alerts (can be same as sender)

Gmail App Password Setup:
    1. Go to https://myaccount.google.com/apppasswords
    2. Generate a new app password for "Mail"
    3. Use that 16-character password here

Usage:
    from email_notifications import EmailNotifier
    notifier = EmailNotifier()
    notifier.send_alert("Driver Failed", "Message to Group X failed at 08:00")
"""

import smtplib
import logging
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

# Load .env file
load_dotenv()

logger = logging.getLogger(__name__)

# Email Configuration - Set via environment variables (NOT in code!)
# Create ~/.whatsapp-scheduler-email with your credentials
EMAIL_CONFIG = {
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': 587,
    'sender_email': os.environ.get('EMAIL_USER', ''),
    'sender_password': os.environ.get('EMAIL_PASS', ''),
    'recipient_email': os.environ.get('EMAIL_TO', ''),
    'subject_prefix': 'RPI-3B+ Home Server',  # Custom subject prefix
    'enabled': True,
}


class EmailNotifier:
    """
    Email notification service for WhatsApp Scheduler alerts
    
    Sends formatted HTML emails for various alert types:
    - send_failure: Message/poll failed to send
    - driver_restart: Driver was automatically restarted
    - driver_unresponsive: Driver not responding
    - critical_error: Unexpected errors
    """
    
    def __init__(self, config: Optional[dict] = None):
        """
        Initialize email notifier
        
        Args:
            config: Optional config dict override. If None, uses EMAIL_CONFIG
        """
        self.config = config or EMAIL_CONFIG
        self._last_email_time = {}  # Rate limiting per subject
        self._rate_limit_seconds = 300  # Don't send same alert more than once per 5 min
    
    def is_configured(self) -> bool:
        """Check if email is properly configured"""
        return bool(
            self.config.get('enabled') and
            self.config.get('sender_email') and
            self.config.get('sender_password') and
            self.config.get('recipient_email')
        )
    
    def send_alert(self, subject: str, message: str, alert_type: str = 'general') -> bool:
        """
        Send an email alert
        
        Args:
            subject: Email subject line
            message: Alert message body
            alert_type: Type of alert for categorization
            
        Returns:
            bool: True if email sent successfully, False otherwise
        """
        if not self.is_configured():
            logger.debug("Email notifications not configured - skipping")
            return False
        
        # Rate limiting - don't spam the same alert
        rate_key = f"{alert_type}:{subject}"
        now = datetime.now().timestamp()
        last_sent = self._last_email_time.get(rate_key, 0)
        
        if now - last_sent < self._rate_limit_seconds:
            logger.debug(f"Rate limiting email: {subject}")
            return False
        
        try:
            # Create email
            msg = MIMEMultipart('alternative')
            subject_prefix = self.config.get('subject_prefix', 'WhatsApp Scheduler')
            msg['Subject'] = f"[{subject_prefix}] ERROR: {subject}"
            msg['From'] = self.config['sender_email']
            msg['To'] = self.config['recipient_email']
            
            # Plain text version
            text_body = f"""
{subject_prefix} Alert
========================

ERROR: {subject}

Type: {alert_type}
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

{message}

---
Automated alert from WhatsApp Scheduler on Raspberry Pi.
            """
            
            # HTML version
            html_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background-color: #dc3545; color: white; padding: 20px; border-radius: 5px 5px 0 0;">
                    <h2 style="margin: 0;">⚠️ {subject_prefix}</h2>
                    <p style="margin: 5px 0 0 0; font-size: 14px;">ERROR: {subject}</p>
                </div>
                <div style="padding: 20px; border: 1px solid #ddd; border-top: none;">
                    <table style="width: 100%; margin-bottom: 20px;">
                        <tr>
                            <td style="font-weight: bold; width: 80px;">Type:</td>
                            <td>{alert_type}</td>
                        </tr>
                        <tr>
                            <td style="font-weight: bold;">Time:</td>
                            <td>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</td>
                        </tr>
                    </table>
                    <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; white-space: pre-wrap;">
{message}
                    </div>
                </div>
                <div style="padding: 10px; text-align: center; color: #666; font-size: 12px;">
                    Automated alert from WhatsApp Scheduler on Raspberry Pi
                </div>
            </body>
            </html>
            """
            
            msg.attach(MIMEText(text_body, 'plain'))
            msg.attach(MIMEText(html_body, 'html'))
            
            # Send email
            with smtplib.SMTP(self.config['smtp_server'], self.config['smtp_port']) as server:
                server.starttls()
                server.login(self.config['sender_email'], self.config['sender_password'])
                server.send_message(msg)
            
            self._last_email_time[rate_key] = now
            logger.info(f"✉️ Alert email sent: {subject}")
            return True
            
        except smtplib.SMTPAuthenticationError:
            logger.error("Email authentication failed - check your app password")
            return False
        except Exception as e:
            logger.error(f"Failed to send email alert: {e}")
            return False
    
    def send_failure_alert(self, contact: str, content_type: str, error: str):
        """Send alert for failed message/poll send"""
        self.send_alert(
            subject=f"Failed to send {content_type} to {contact}",
            message=f"Contact: {contact}\nType: {content_type}\nError: {error}",
            alert_type='send_failure'
        )
    
    def send_driver_restart_alert(self, reason: str):
        """Send alert when driver is automatically restarted"""
        self.send_alert(
            subject="Driver Auto-Restarted",
            message=f"The WhatsApp driver was automatically restarted.\n\nReason: {reason}",
            alert_type='driver_restart'
        )
    
    def send_driver_unresponsive_alert(self, failure_count: int):
        """Send alert when driver is unresponsive"""
        self.send_alert(
            subject="Driver Unresponsive",
            message=f"The WhatsApp driver has failed {failure_count} consecutive health checks.\n\nThis may indicate:\n- Chromium crashed\n- WhatsApp session expired\n- Memory exhaustion",
            alert_type='driver_unresponsive'
        )
    
    def send_critical_error_alert(self, error: str):
        """Send alert for critical errors"""
        self.send_alert(
            subject="Critical Error",
            message=f"A critical error occurred:\n\n{error}",
            alert_type='critical_error'
        )


# Singleton instance for easy import
_notifier = None

def get_notifier() -> EmailNotifier:
    """Get or create the email notifier singleton"""
    global _notifier
    if _notifier is None:
        _notifier = EmailNotifier()
    return _notifier


if __name__ == "__main__":
    # Test the email notifier
    print("Testing Email Notifier...")
    print(f"Configured: {get_notifier().is_configured()}")
    
    if get_notifier().is_configured():
        print("Sending test email...")
        success = get_notifier().send_alert(
            subject="Test Alert",
            message="This is a test alert from your WhatsApp Scheduler.",
            alert_type='test'
        )
        print(f"Email sent: {success}")
    else:
        print("\nEmail not configured. Set these environment variables:")
        print("  export EMAIL_SENDER='your-email@gmail.com'")
        print("  export EMAIL_PASSWORD='your-app-password'")
        print("  export EMAIL_RECIPIENT='your-email@gmail.com'")
