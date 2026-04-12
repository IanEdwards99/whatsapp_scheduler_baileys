"""
Message History Tracking
Tracks all sent messages and polls with automatic size limit enforcement
"""

import json
import os
from filelock import FileLock
from datetime import datetime
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class MessageHistory:
    """Track all sent messages with size limit and file locking"""

    MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10MB

    def __init__(self, history_file: str = "schedules/message_history.json"):
        self.history_file = history_file
        self._lock = FileLock(f"{history_file}.lock", timeout=10)
        self._ensure_file()

    def _ensure_file(self):
        """Create history file if it doesn't exist"""
        if not os.path.exists(self.history_file):
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
            with open(self.history_file, 'w') as f:
                json.dump([], f)
            logger.info(f"Created message history file: {self.history_file}")

    def _check_size_and_prune(self):
        """Check file size and prune if over limit"""
        try:
            if os.path.getsize(self.history_file) > self.MAX_SIZE_BYTES:
                logger.warning(f"History file exceeds {self.MAX_SIZE_BYTES / (1024*1024):.1f}MB, pruning...")
                history = self._load_history_locked()
                pruned = history[len(history)//2:]
                self._save_history_locked(pruned)
                logger.info(f"Pruned history from {len(history)} to {len(pruned)} entries")
        except Exception as e:
            logger.error(f"Error pruning history: {e}")

    def _load_history_locked(self) -> List[Dict]:
        """Load history with file lock"""
        self._ensure_file()
        with self._lock:
            try:
                with open(self.history_file, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                logger.error("Error decoding history JSON, returning empty list")
                return []

    def _save_history_locked(self, history: List[Dict]):
        """Save history with file lock"""
        with self._lock:
            with open(self.history_file, 'w') as f:
                json.dump(history, f, indent=2)
    
    def load_history(self) -> List[Dict]:
        """Load message history (public method without lock)"""
        try:
            return self._load_history_locked()
        except Exception as e:
            logger.error(f"Error loading history: {e}")
            return []
    
    def add_entry(self, entry_type: str, contact: str, content: Dict, status: str, metadata: Optional[Dict] = None):
        """
        Add a history entry
        
        Args:
            entry_type: 'message' or 'poll'
            contact: Contact name or JID
            content: Message content (dict with 'message' or 'question'/'options')
            status: 'sent', 'failed', 'error'
            metadata: Optional additional data (schedule info, error details, etc.)
        """
        now = datetime.now()
        
        entry = {
            'type': entry_type,
            'contact': contact,
            'content': content,
            'status': status,
            'timestamp': now.isoformat(),
            'date': now.strftime("%Y-%m-%d %H:%M:%S"),
            'metadata': metadata or {}
        }
        
        try:
            history = self._load_history_locked()
            history.append(entry)
            self._save_history_locked(history)
            
            logger.info(f"Added history entry: {entry_type} to {contact} [{status}]")
            
            # Check size after adding
            self._check_size_and_prune()
            
        except Exception as e:
            logger.error(f"Failed to add history entry: {e}")
    
    def get_recent(self, limit: int = 100) -> List[Dict]:
        """Get most recent entries"""
        history = self.load_history()
        return history[-limit:] if history else []
    
    def get_by_contact(self, contact: str, limit: int = 50) -> List[Dict]:
        """Get history for a specific contact"""
        history = self.load_history()
        filtered = [entry for entry in history if entry.get('contact') == contact]
        return filtered[-limit:] if filtered else []
    
    def get_by_status(self, status: str, limit: int = 50) -> List[Dict]:
        """Get history entries by status"""
        history = self.load_history()
        filtered = [entry for entry in history if entry.get('status') == status]
        return filtered[-limit:] if filtered else []
    
    def get_stats(self) -> Dict:
        """Get statistics about message history"""
        history = self.load_history()
        
        total = len(history)
        sent = sum(1 for e in history if e.get('status') == 'sent')
        failed = sum(1 for e in history if e.get('status') == 'failed')
        errors = sum(1 for e in history if e.get('status') == 'error')
        
        messages = sum(1 for e in history if e.get('type') == 'message')
        polls = sum(1 for e in history if e.get('type') == 'poll')
        
        return {
            'total': total,
            'sent': sent,
            'failed': failed,
            'errors': errors,
            'messages': messages,
            'polls': polls,
            'success_rate': (sent / total * 100) if total > 0 else 0
        }
