import json
import fcntl
import logging
import requests
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import contextmanager
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ScheduleLock:
    """Context manager for file locking"""
    
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.lockfile = f"{filepath}.lock"
        self.lock_fd = None
    
    def __enter__(self):
        # Create lock file if it doesn't exist
        Path(self.lockfile).touch()
        self.lock_fd = open(self.lockfile, 'w')
        fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_EX)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.lock_fd:
            fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_UN)
            self.lock_fd.close()


class MessageScheduler:
    """Enhanced scheduler with status tracking, recurring logic, and file locking"""
    
    def __init__(self, schedule_file: str):
        self.schedule_file = schedule_file
        self.driver_server_url = os.environ.get("DRIVER_URL", "http://127.0.0.1:5002")
        
        # Ensure schedule file exists
        Path(schedule_file).parent.mkdir(parents=True, exist_ok=True)
        if not Path(schedule_file).exists():
            with open(schedule_file, 'w') as f:
                json.dump([], f)
    
    def _load_schedules_locked(self) -> List[Dict]:
        """Load schedules with file locking"""
        with ScheduleLock(self.schedule_file):
            try:
                with open(self.schedule_file, 'r') as f:
                    return json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                return []
    
    def _save_schedules_locked(self, schedules: List[Dict]):
        """Save schedules with file locking"""
        with ScheduleLock(self.schedule_file):
            with open(self.schedule_file, 'w') as f:
                json.dump(schedules, f, indent=2)
    
    def load_schedules(self) -> List[Dict]:
        """Public method to load schedules"""
        return self._load_schedules_locked()
    
    def save_schedules(self, schedules: List[Dict]):
        """Public method to save schedules"""
        self._save_schedules_locked(schedules)
    
    def _calculate_next_run(self, current_time_str: str, recurring: str) -> str:
        """Calculate next run time based on recurring pattern"""
        try:
            current = datetime.strptime(current_time_str, "%H:%M")
            now = datetime.now()
            current_full = now.replace(hour=current.hour, minute=current.minute, second=0, microsecond=0)
            
            if recurring == "daily":
                next_run = current_full + timedelta(days=1)
            elif recurring == "weekly":
                next_run = current_full + timedelta(weeks=1)
            elif recurring == "monthly":
                # Approximate month as 30 days
                next_run = current_full + timedelta(days=30)
            else:
                return current_time_str
            
            return next_run.strftime("%H:%M")
        except Exception as e:
            logger.error(f"Error calculating next run: {e}")
            return current_time_str
    
    def add_message_schedule(self, contact: str, message: str, schedule_datetime: str, recurring: Optional[str] = None):
        """Add a message schedule with status tracking
        
        Args:
            contact: Phone number or group name
            message: Message text
            schedule_datetime: Full datetime string (YYYY-MM-DDTHH:MM or ISO format)
            recurring: None, 'daily', 'weekly', or 'monthly'
        """
        schedules = self._load_schedules_locked()
        
        # Parse the datetime - handle both 'YYYY-MM-DDTHH:MM' (from HTML) and ISO format
        try:
            if 'T' in schedule_datetime and len(schedule_datetime) == 16:
                # HTML datetime-local format: 2025-12-14T19:30
                dt = datetime.strptime(schedule_datetime, "%Y-%m-%dT%H:%M")
            else:
                # Try ISO format or fallback to just time
                dt = datetime.fromisoformat(schedule_datetime) if '-' in schedule_datetime else None
        except:
            dt = None
        
        # Store as ISO format for full datetime support
        next_run = dt.isoformat() if dt else schedule_datetime
        time_only = dt.strftime("%H:%M") if dt else schedule_datetime
        
        schedule = {
            'type': 'message',
            'contact': contact,
            'message': message,
            'time': time_only,  # Keep for display (HH:MM)
            'recurring': recurring,
            'status': 'pending',
            'next_run': next_run,  # Full datetime ISO
            'last_run': None,
            'attempts': 0,
            'created_at': datetime.now().isoformat()
        }
        
        schedules.append(schedule)
        self._save_schedules_locked(schedules)
        logger.info(f"Added message schedule for {contact} at {next_run}")
    
    def add_poll_schedule(self, contact: str, question: str, options: List[str], schedule_datetime: str, recurring: Optional[str] = None, allow_multi_select: bool = False):
        """Add a poll schedule with status tracking
        
        Args:
            contact: Phone number or group name
            question: Poll question
            options: List of poll options
            schedule_datetime: Full datetime string (YYYY-MM-DDTHH:MM or ISO format)
            recurring: None, 'daily', 'weekly', or 'monthly'
            allow_multi_select: Whether to allow multiple option selection
        """
        schedules = self._load_schedules_locked()
        
        # Parse the datetime - handle both 'YYYY-MM-DDTHH:MM' (from HTML) and ISO format
        try:
            if 'T' in schedule_datetime and len(schedule_datetime) == 16:
                # HTML datetime-local format: 2025-12-14T19:30
                dt = datetime.strptime(schedule_datetime, "%Y-%m-%dT%H:%M")
            else:
                # Try ISO format or fallback to just time
                dt = datetime.fromisoformat(schedule_datetime) if '-' in schedule_datetime else None
        except:
            dt = None
        
        # Store as ISO format for full datetime support
        next_run = dt.isoformat() if dt else schedule_datetime
        time_only = dt.strftime("%H:%M") if dt else schedule_datetime
        
        schedule = {
            'type': 'poll',
            'contact': contact,
            'question': question,
            'options': options,
            'time': time_only,  # Keep for display (HH:MM)
            'recurring': recurring,
            'allow_multi_select': allow_multi_select,
            'status': 'pending',
            'next_run': next_run,  # Full datetime ISO
            'last_run': None,
            'attempts': 0,
            'created_at': datetime.now().isoformat()
        }
        
        schedules.append(schedule)
        self._save_schedules_locked(schedules)
        logger.info(f"Added poll schedule for {contact} at {next_run}")
    
    def update_schedule(self, index: int, data: dict):
        """Update an existing schedule by index
        
        Args:
            index: Schedule index to update
            data: Dict with updated fields (type, contact, message/question, datetime, recurring, etc.)
        """
        schedules = self._load_schedules_locked()
        
        if 0 <= index < len(schedules):
            schedule = schedules[index]
            schedule_datetime = data.get('datetime', '')
            
            # Parse the datetime
            try:
                if 'T' in schedule_datetime and len(schedule_datetime) == 16:
                    dt = datetime.strptime(schedule_datetime, "%Y-%m-%dT%H:%M")
                else:
                    dt = datetime.fromisoformat(schedule_datetime) if '-' in schedule_datetime else None
            except:
                dt = None
            
            next_run = dt.isoformat() if dt else schedule_datetime
            time_only = dt.strftime("%H:%M") if dt else schedule_datetime
            
            # Update common fields
            schedule['type'] = data.get('type', schedule['type'])
            schedule['contact'] = data.get('contact', schedule['contact'])
            schedule['time'] = time_only
            schedule['recurring'] = data.get('recurring') or None
            schedule['next_run'] = next_run
            schedule['status'] = 'pending'  # Reset to pending after edit
            schedule['attempts'] = 0
            
            # Update type-specific fields
            if data.get('type') == 'message':
                schedule['message'] = data.get('message', '')
                # Remove poll fields if switching types
                schedule.pop('question', None)
                schedule.pop('options', None)
                schedule.pop('allow_multi_select', None)
            elif data.get('type') == 'poll':
                schedule['question'] = data.get('question', '')
                schedule['options'] = data.get('options', [])
                schedule['allow_multi_select'] = data.get('allow_multi_select', False)
                # Remove message field if switching types
                schedule.pop('message', None)
            
            self._save_schedules_locked(schedules)
            logger.info(f"Updated schedule {index}: {schedule['contact']} at {next_run}")
            return schedule
        return None
    
    def remove_schedule(self, index: int):
        """Remove a schedule by index"""
        schedules = self._load_schedules_locked()
        if 0 <= index < len(schedules):
            removed = schedules.pop(index)
            self._save_schedules_locked(schedules)
            logger.info(f"Removed schedule: {removed.get('contact')} at {removed.get('time')}")
            return removed
        return None
    
    def mark_completed(self, index: int, success: bool = True):
        """Mark a schedule as completed and handle recurring logic"""
        schedules = self._load_schedules_locked()
        
        if 0 <= index < len(schedules):
            schedule = schedules[index]
            now = datetime.now()
            schedule['last_run'] = now.isoformat()
            schedule['status'] = 'completed' if success else 'failed'
            
            # If recurring, calculate next run time as full datetime and set status back to pending
            if success and schedule.get('recurring'):
                # Calculate the next run based on current time + recurring interval
                next_time_str = self._calculate_next_run(schedule['time'], schedule['recurring'])
                
                # Parse to get next full datetime
                next_hour, next_min = map(int, next_time_str.split(':'))
                next_run_dt = now.replace(hour=next_hour, minute=next_min, second=0, microsecond=0)
                
                # If the calculated time is in the past, add the interval again
                if next_run_dt <= now:
                    if schedule['recurring'] == 'daily':
                        next_run_dt += timedelta(days=1)
                    elif schedule['recurring'] == 'weekly':
                        next_run_dt += timedelta(weeks=1)
                    elif schedule['recurring'] == 'monthly':
                        next_run_dt += timedelta(days=30)
                
                # Update the same schedule entry instead of creating a new one
                schedule['next_run'] = next_run_dt.isoformat()
                schedule['status'] = 'pending'
                schedule['attempts'] = 0
                
                logger.info(f"Next occurrence scheduled: {schedule['contact']} at {next_run_dt.strftime('%Y-%m-%d %H:%M')}")
            
            self._save_schedules_locked(schedules)
    
    def get_pending_schedules(self) -> List[tuple]:
        """Get all pending schedules that should run now"""
        schedules = self._load_schedules_locked()
        now = datetime.now()
        
        pending = []
        for idx, schedule in enumerate(schedules):
            # Only process schedules with 'pending' status
            if schedule.get('status') != 'pending':
                continue
            
            # Get the scheduled time
            next_run = schedule.get('next_run')
            schedule_time = schedule.get('time')
            
            # Check if it's time to run
            should_run = False
            
            if next_run:
                # If next_run is a full ISO datetime, compare datetimes
                try:
                    next_run_dt = datetime.fromisoformat(next_run)
                    should_run = now >= next_run_dt
                except (ValueError, TypeError):
                    # If next_run is just HH:MM format, compare times
                    if isinstance(next_run, str) and ':' in next_run:
                        current_time = now.strftime("%H:%M")
                        should_run = current_time >= next_run
            elif schedule_time:
                # Fallback to time field if next_run is not set
                current_time = now.strftime("%H:%M")
                should_run = current_time >= schedule_time
            
            if should_run:
                pending.append((idx, schedule))
        
        return pending
    
    def _resolve_group_name(self, contact: str) -> str:
        """Resolve group name to JID"""
        if '@' in contact:
            return contact
        
        try:
            response = requests.get(f"{self.driver_server_url}/get_groups", timeout=30)
            if response.status_code == 200:
                groups = response.json().get('groups', [])
                for group in groups:
                    if group['name'].lower() == contact.lower():
                        logger.info(f"Resolved '{contact}' to '{group['id']}'")
                        return group['id']
        except requests.Timeout:
            logger.warning(f"Timeout resolving group '{contact}' - driver may be slow or unresponsive")
        except Exception as e:
            logger.warning(f"Error resolving group: {e}")
        
        return contact
    
    def send_message_via_api(self, contact: str, message: str):
        """Send message via driver API. Returns (True, None) on success or (False, error_detail) on failure."""
        try:
            resolved = self._resolve_group_name(contact)
            response = requests.post(
                f"{self.driver_server_url}/send_message",
                json={"contact": resolved, "message": message},
                timeout=30
            )
            if response.status_code == 200:
                logger.info(f"✓ Message sent to {contact}")
                return True, None
            else:
                detail = self._parse_error_response(response, contact)
                logger.error(f"✗ Failed: {detail}")
                return False, detail
        except Exception as e:
            logger.error(f"✗ Error: {e}")
            return False, str(e)
    
    def send_poll_via_api(self, contact: str, question: str, options: List[str], allow_multi_select: bool = False):
        """Send poll via driver API. Returns (True, None) on success or (False, error_detail) on failure."""
        try:
            resolved = self._resolve_group_name(contact)
            response = requests.post(
                f"{self.driver_server_url}/send_poll",
                json={"contact": resolved, "question": question, "options": options, "allowMultiSelect": allow_multi_select},
                timeout=30
            )
            if response.status_code == 200:
                logger.info(f"✓ Poll sent to {contact}")
                return True, None
            else:
                detail = self._parse_error_response(response, contact)
                logger.error(f"✗ Failed: {detail}")
                return False, detail
        except Exception as e:
            logger.error(f"✗ Error: {e}")
            return False, str(e)

    @staticmethod
    def _parse_error_response(response, contact: str) -> str:
        """Extract a human-readable error from the driver's JSON error response."""
        try:
            data = response.json()
            parts = []
            if data.get('message'):
                parts.append(data['message'])
            if data.get('chatId'):
                parts.append(f"Chat ID used: {data['chatId']}")
            if data.get('hint'):
                parts.append(data['hint'])
            return ' | '.join(parts) if parts else response.text
        except Exception:
            return response.text

    def stop(self):
        """Stop method for shutting down operations cleanly."""
        logger.info("Scheduler stop method called.")
        pass

