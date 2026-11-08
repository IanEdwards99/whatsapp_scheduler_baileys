import json
import logging
import os
import re
import tempfile
from calendar import monthrange
from datetime import datetime, time, timedelta, timezone as utc_timezone
from hashlib import sha256
from pathlib import Path
from typing import List
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from filelock import FileLock

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SCHEDULE_FILE = Path(__file__).resolve().parent / "schedules" / "schedule.json"
RECURRENCES = ("daily", "weekly", "monthly")
STATUS_CONTACT = "WhatsApp Status"
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


def status_link(value):
    link = value.strip() if isinstance(value, str) else ""
    error = ValueError("Enter one HTTPS link to a YouTube video or channel livestream.")
    if not link or re.search(r'[\s<>"\x00-\x1f]', link):
        raise error
    try:
        url = urlsplit(link)
    except ValueError:
        raise error from None
    if url.scheme != "https" or url.netloc.lower() not in YOUTUBE_HOSTS:
        raise error
    parts = url.path.strip("/").split("/")
    video = ""
    if url.hostname == "youtu.be":
        video = parts[0]
    elif parts[0] == "watch":
        video = parse_qs(url.query, keep_blank_values=True).get("v", [""])[0]
    elif parts[0] in ("live", "shorts", "embed") and len(parts) > 1:
        video = parts[1]
    elif re.fullmatch(r"/(?:@[^/]+|(?:channel|c|user)/[^/]+)/live/?", url.path):
        return link
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
        raise error
    return link


def status_audience(value):
    entries = re.split(r"[,\n]", value) if isinstance(value, str) else value
    if not isinstance(entries, list) or any(not isinstance(entry, str) for entry in entries):
        raise ValueError("Enter international phone numbers beginning with + and a country code.")
    numbers = []
    for entry in entries:
        if not entry.strip():
            continue
        number = re.sub(r"[ ().-]", "", entry.strip())
        if not re.fullmatch(r"\+[1-9][0-9]{6,14}", number):
            raise ValueError("Enter international phone numbers beginning with + and a country code.")
        numbers.append(number)
    numbers = list(dict.fromkeys(numbers))
    if not 1 <= len(numbers) <= 50:
        raise ValueError("Choose between 1 and 50 Status viewers.")
    return numbers


def schedule_revision(schedule):
    return sha256(json.dumps(schedule, sort_keys=True).encode()).hexdigest()


def schedule_zone(name):
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Enter an IANA timezone such as Africa/Johannesburg or Europe/Amsterdam.") from None


def schedule_datetime(schedule):
    value = schedule.get("next_run") or schedule["time"]
    zone = schedule_zone(schedule.get("timezone"))
    if "T" not in value and len(value) <= 8:
        return datetime.combine(datetime.now(zone).date(), time.fromisoformat(value), tzinfo=zone)
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if zone:
        return result.astimezone(zone) if result.tzinfo else result.replace(tzinfo=zone)
    return result


def schedule_label(schedule):
    try:
        value = schedule_datetime(schedule)
    except (KeyError, TypeError, ValueError):
        return f"Invalid schedule time ({schedule.get('next_run') or schedule.get('time') or 'missing'})"
    zone = schedule.get("timezone") or value.tzname() or "server local time"
    return f"{value:%Y-%m-%d %H:%M} ({zone})"


def _instant(value):
    return value.astimezone(utc_timezone.utc)


def _timing(value, recurring, timezone):
    recurring = recurring or None
    if recurring is not None and recurring not in RECURRENCES:
        raise ValueError("Repeat must be daily, weekly, monthly, or none.")
    timezone = (timezone or "").strip()
    zone = schedule_zone(timezone)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        if timezone:
            raise ValueError("Enter a date and time, for example 2026-11-15 08:30.") from None
        try:
            value = time.fromisoformat(value).strftime("%H:%M")
        except ValueError:
            raise ValueError("Enter a date and time, for example 2026-11-15 08:30.") from None
        return {"time": value, "next_run": value, "recurring": recurring, "timezone": None}

    if "T" not in value and " " not in value:
        raise ValueError("Enter both a date and a time.")
    if zone:
        if dt.tzinfo:
            dt = dt.astimezone(zone)
        else:
            dt = dt.replace(tzinfo=zone)
            if _instant(dt).astimezone(zone).replace(tzinfo=None) != dt.replace(tzinfo=None):
                raise ValueError("That local time is skipped by a clock change. Choose another time.")

    timing = {"time": dt.strftime("%H:%M"), "next_run": dt.isoformat(),
              "recurring": recurring, "timezone": timezone or None}
    if recurring == "monthly":
        timing["month_day"] = dt.day
    return timing


def _next_occurrence(schedule, now):
    due = schedule_datetime(schedule)
    zone = due.tzinfo
    local_now = now.astimezone(zone) if zone else now
    day = due.date()
    wall_time = time.fromisoformat(schedule["time"])
    recurring = schedule["recurring"]
    while True:
        if recurring == "monthly":
            year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
            day = day.replace(year=year, month=month, day=min(
                schedule.get("month_day", due.day), monthrange(year, month)[1]
            ))
        else:
            day += timedelta(days=7 if recurring == "weekly" else 1)
        candidate = datetime.combine(day, wall_time, tzinfo=zone)
        if _instant(candidate) > _instant(local_now):
            # Round-trip through UTC to advance nonexistent local times on spring-forward days.
            return _instant(candidate).astimezone(zone) if zone else candidate


class MessageScheduler:
    """Share one atomic JSON queue across the web app, bot and scheduler."""

    def __init__(self, schedule_file=SCHEDULE_FILE):
        self.schedule_file = Path(schedule_file)
        self.schedule_file.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(f"{self.schedule_file}.lock", timeout=10)
        self.driver_server_url = os.environ.get("DRIVER_URL", "http://127.0.0.1:5001")

    def _read(self):
        try:
            with self.schedule_file.open(encoding="utf-8") as file:
                schedules = json.load(file)
        except FileNotFoundError:
            return []
        missing_ids = [schedule for schedule in schedules if not schedule.get("id")]
        if missing_ids:
            for schedule in missing_ids:
                schedule["id"] = uuid4().hex
            self._write(schedules)
        return schedules

    def _write(self, schedules):
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False,
                                         dir=self.schedule_file.parent) as file:
            temporary = Path(file.name)
            try:
                json.dump(schedules, file, indent=2)
                file.close()
                temporary.replace(self.schedule_file)
            finally:
                temporary.unlink(missing_ok=True)

    def load_schedules(self):
        with self.lock:
            return self._read()

    def save_schedules(self, schedules):
        with self.lock:
            self._write(schedules)

    def _add(self, content, schedule_datetime, recurring, timezone):
        schedule = {
            **content, **_timing(schedule_datetime, recurring, timezone),
            "id": uuid4().hex, "status": "pending", "last_run": None,
            "attempts": 0, "created_at": datetime.now().isoformat(),
        }
        with self.lock:
            schedules = self._read()
            schedules.append(schedule)
            self._write(schedules)
        return schedule

    def add_message_schedule(self, contact, message, schedule_datetime, recurring=None, timezone=None):
        return self._add({"type": "message", "contact": contact, "message": message},
                         schedule_datetime, recurring, timezone)

    def add_status_schedule(self, link, audience, schedule_datetime, recurring=None, timezone=None):
        return self._add({"type": "status", "contact": STATUS_CONTACT, "message": status_link(link),
                          "audience": status_audience(audience)}, schedule_datetime, recurring, timezone)

    def add_poll_schedule(self, contact, question, options, schedule_datetime, recurring=None,
                          allow_multi_select=False, timezone=None):
        return self._add({
            "type": "poll", "contact": contact, "question": question, "options": options,
            "allow_multi_select": allow_multi_select,
        }, schedule_datetime, recurring, timezone)

    @staticmethod
    def _index(schedules, key):
        if isinstance(key, int):
            return key if 0 <= key < len(schedules) else None
        return next((index for index, item in enumerate(schedules) if item["id"] == key), None)

    def update_schedule(self, key, data, expected=None):
        with self.lock:
            schedules = self._read()
            index = self._index(schedules, key)
            if index is None:
                return None
            schedule = schedules[index]
            if expected is not None and schedule_revision(schedule) != expected:
                return None

            if {"datetime", "recurring", "timezone"} & data.keys():
                try:
                    current = schedule_datetime(schedule)
                except (KeyError, TypeError, ValueError):
                    if not data.get("datetime"):
                        raise ValueError("Enter a valid date and time for this schedule.") from None
                    current = None
                value = data["datetime"] if "datetime" in data else current.isoformat()
                recurring = data.get("recurring", schedule.get("recurring"))
                timezone = data.get("timezone", schedule.get("timezone"))
                if "timezone" in data and "datetime" not in data:
                    value = current.replace(tzinfo=None).isoformat()
                timing = _timing(value, recurring, timezone)
                if (recurring == "monthly" and current and
                        current.replace(tzinfo=None) == schedule_datetime(timing).replace(tzinfo=None)):
                    timing["month_day"] = schedule.get("month_day", current.day)
                schedule.pop("month_day", None)
                schedule.update(timing)

            schedule.update({field: data[field] for field in
                             ("type", "contact", "message", "question", "options", "allow_multi_select", "audience")
                             if field in data})
            if schedule["type"] == "status":
                schedule.update(contact=STATUS_CONTACT, message=status_link(schedule.get("message")),
                                audience=status_audience(schedule.get("audience")))
            else:
                schedule.pop("audience", None)
            if schedule["type"] in ("message", "status"):
                for field in ("question", "options", "allow_multi_select"):
                    schedule.pop(field, None)
            else:
                schedule.pop("message", None)
            schedule.update(status="pending", attempts=0)
            self._write(schedules)
            return schedule

    def remove_schedule(self, key, expected=None):
        with self.lock:
            schedules = self._read()
            index = self._index(schedules, key)
            if index is None or (expected is not None and schedule_revision(schedules[index]) != expected):
                return None
            removed = schedules.pop(index)
            self._write(schedules)
            return removed

    @staticmethod
    def _complete(schedule, success):
        now = datetime.now()
        schedule.update(last_run=now.isoformat(), status="completed" if success else "failed")
        if success and schedule.get("recurring"):
            if schedule["recurring"] == "monthly":
                schedule.setdefault("month_day", schedule_datetime(schedule).day)
            next_run = _next_occurrence(schedule, now)
            schedule.update(next_run=next_run.isoformat(), status="pending", attempts=0)

    def mark_completed(self, key, success=True):
        with self.lock:
            schedules = self._read()
            index = self._index(schedules, key)
            if index is not None:
                self._complete(schedules[index], success)
                self._write(schedules)

    def get_pending_schedules(self):
        now = datetime.now(utc_timezone.utc)
        pending = []
        for index, schedule in enumerate(self.load_schedules()):
            if schedule.get("status", "pending") != "pending":
                continue
            try:
                due = _instant(schedule_datetime(schedule))
                if due <= now:
                    pending.append((due, index, schedule))
            except (KeyError, TypeError, ValueError) as error:
                logger.error("Invalid schedule %s: %s", schedule["id"], error)
        return [(index, schedule) for _, index, schedule in sorted(pending, key=lambda item: item[0])]

    def process_due(self, snapshot, send):
        """Serialize each send with queue edits and recheck the occurrence under the lock."""
        with self.lock:
            schedules = self._read()
            index = self._index(schedules, snapshot["id"])
            if index is None or schedules[index] != snapshot:
                return None
            schedule = schedules[index]
            success = send(schedule)
            self._complete(schedule, success)
            self._write(schedules)
            return success


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

    def post_status_via_api(self, link, audience):
        """Post a link to Status through the driver, with the chosen viewer list."""
        try:
            response = requests.post(
                f"{self.driver_server_url}/post_status",
                json={"link": status_link(link), "audience": status_audience(audience)},
                timeout=(3, 60),
            )
            if response.status_code == 200:
                return True, None
            return False, self._parse_error_response(response, STATUS_CONTACT)
        except (ValueError, requests.RequestException) as error:
            return False, str(error)
    
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

