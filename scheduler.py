import json
import requests
from typing import List, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MessageScheduler:
    """Manages WhatsApp message schedules"""
    
    def __init__(self, schedule_file: str):
        self.schedule_file = schedule_file
        self.schedules = self.load_schedules()
        self.driver_server_url = "http://127.0.0.1:5002"
    
    def load_schedules(self) -> List[dict]:
        """Load schedules from JSON file"""
        try:
            with open(self.schedule_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []
    
    def save_schedules(self):
        """Save schedules to JSON file"""
        with open(self.schedule_file, 'w') as f:
            json.dump(self.schedules, f, indent=2)
    
    def add_message_schedule(self, contact: str, message: str, time: str, recurring: Optional[str] = None):
        """Add a message schedule"""
        schedule = {
            'type': 'message',
            'contact': contact,
            'message': message,
            'time': time,
            'recurring': recurring
        }
        self.schedules.append(schedule)
        self.save_schedules()
        logger.info(f"Added message schedule for {contact} at {time}")
    
    def add_poll_schedule(self, contact: str, question: str, options: List[str], time: str, recurring: Optional[str] = None, allow_multi_select: bool = False):
        """Add a poll schedule"""
        schedule = {
            'type': 'poll',
            'contact': contact,
            'question': question,
            'options': options,
            'time': time,
            'recurring': recurring,
            'allow_multi_select': allow_multi_select
        }
        self.schedules.append(schedule)
        self.save_schedules()
        logger.info(f"Added poll schedule for {contact} at {time}")
    
    def remove_schedule(self, index: int):
        """Remove a schedule by index"""
        if 0 <= index < len(self.schedules):
            self.schedules.pop(index)
            self.save_schedules()
            logger.info(f"Removed schedule at index {index}")
    
    def list_schedules(self) -> List[dict]:
        """List all schedules"""
        return self.schedules
    
    def send_message_via_api(self, contact: str, message: str) -> bool:
        """Send a message through the driver server API"""
        try:
            # Try to resolve group name to JID
            resolved_contact = self._resolve_group_name(contact)
            
            response = requests.post(
                f"{self.driver_server_url}/send_message",
                json={"contact": resolved_contact, "message": message},
                timeout=30
            )
            if response.status_code == 200:
                logger.info(f"Message sent to {contact}")
                return True
            else:
                logger.error(f"Failed to send message: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return False
    
    def send_poll_via_api(self, contact: str, question: str, options: List[str], allow_multi_select: bool = False) -> bool:
        """Send a poll through the driver server API"""
        try:
            # Try to resolve group name to JID
            resolved_contact = self._resolve_group_name(contact)
            
            response = requests.post(
                f"{self.driver_server_url}/send_poll",
                json={"contact": resolved_contact, "question": question, "options": options, "allowMultiSelect": allow_multi_select},
                timeout=30
            )
            if response.status_code == 200:
                logger.info(f"Poll sent to {contact}")
                return True
            else:
                logger.error(f"Failed to send poll: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error sending poll: {e}")
            return False
    
    def _resolve_group_name(self, contact: str) -> str:
        """Resolve a group name to its JID, or return contact as-is if it's already a JID"""
        # If it already looks like a JID (contains @), return as-is
        if '@' in contact:
            return contact
        
        try:
            # Fetch groups from driver and search for matching name (case-insensitive)
            response = requests.get(
                f"{self.driver_server_url}/get_groups",
                timeout=30
            )
            if response.status_code == 200:
                data = response.json()
                groups = data.get('groups', [])
                
                # Search for group with matching name (case-insensitive)
                for group in groups:
                    if group['name'].lower() == contact.lower():
                        logger.info(f"Resolved group name '{contact}' to JID '{group['id']}'")
                        return group['id']
                
                logger.warning(f"Group name '{contact}' not found. Using as-is.")
                return contact
            else:
                logger.warning(f"Failed to fetch groups: {response.text}. Using contact as-is.")
                return contact
        except requests.Timeout:
            logger.warning(f"Timeout resolving group '{contact}' - driver may be slow or unresponsive")
            return contact
        except Exception as e:
            logger.warning(f"Error resolving group name: {e}. Using contact as-is.")
            return contact
    
    def process_pending_schedules(self):
        """Process schedules due to be sent (to be called by scheduler)"""
        # This will be called by APScheduler or similar
        for schedule in self.schedules:
            # Time-based logic will be implemented in run_scheduler.py
            pass
