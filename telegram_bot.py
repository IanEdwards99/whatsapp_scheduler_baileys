import os
from datetime import datetime

import telebot
from dotenv import load_dotenv
from filelock import Timeout
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telebot_calendar import Calendar, CallbackData, ENGLISH_LANGUAGE

from scheduler_core import (
    PHONE_STATUS_AUDIENCE, MessageScheduler, schedule_label, schedule_revision, schedule_zone, status_link,
)

load_dotenv()
TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID", "0"))
if CHAT_ID <= 0:
    raise ValueError("Set TELEGRAM_CHAT_ID to your private chat ID.")

bot = telebot.TeleBot(TOKEN, threaded=False)
scheduler = MessageScheduler()
calendar = Calendar(ENGLISH_LANGUAGE)
calendar_data = CallbackData("schedule_date", "action", "year", "month", "day")
state = {}

MENU = {
    "📝 List Schedules": "/list",
    "➕ Add Schedule": "/add",
    "📣 Schedule Status": "/addstatus",
    "✏️ Edit Schedule": "/edit",
    "🗑 Delete Schedule": "/delete",
    "❓ Help": "/help",
}
DATE_PROMPT = "Enter the date and time as YYYY-MM-DD HH:MM, or choose a date below."
ZONE_PROMPT = "Enter a timezone such as Africa/Johannesburg or Europe/Amsterdam, or type local for server time."
REPEAT_PROMPT = "Enter daily, weekly, monthly, or none."
STATUS_LINK_PROMPT = "Paste the YouTube video or livestream link to share on WhatsApp Status."
STATUS_AUDIENCE_PROMPT = (
    "Type default to use your usual WhatsApp Status audience, or enter up to 50 international numbers starting with +."
)
FIELDS = {
    "contact": ("contact", "Enter the contact or WhatsApp group."),
    "message": ("message", "Enter the new message."),
    "link": ("message", STATUS_LINK_PROMPT),
    "viewers": ("audience", STATUS_AUDIENCE_PROMPT),
    "question": ("question", "Enter the new poll question."),
    "options": ("options", "Enter at least two unique options, separated by commas."),
    "multi": ("allow_multi_select", "Allow multiple answers? Enter yes or no."),
    "time": ("datetime", "Enter the new date and time as YYYY-MM-DD HH:MM in the schedule's timezone."),
    "timezone": ("timezone", ZONE_PROMPT + " This keeps the displayed clock time and changes its timezone."),
    "repeat": ("recurring", REPEAT_PROMPT),
}


def authorized(chat):
    return chat.id == CHAT_ID and chat.type == "private"


def reply(text, **kwargs):
    return bot.send_message(CHAT_ID, text, **kwargs)


def show_schedules(schedules):
    if not schedules:
        reply("No schedules found.")
        return
    lines = []
    for index, schedule in schedules.items():
        preview = (schedule.get("message") or schedule.get("question") or "")[:65]
        line = (f"{index}. {schedule_label(schedule)} · {schedule.get('recurring') or 'once'} · "
                f"{schedule.get('status', 'pending')}\n"
                f"{schedule['contact'][:150]} · {preview}\n\n")
        if sum(map(len, lines)) + len(line) > 3500:
            reply("".join(lines))
            lines.clear()
        lines.append(line)
    if lines:
        reply("".join(lines))


def begin(command):
    state.clear()
    if command in ("/list", "/edit", "/delete"):
        schedules = dict(enumerate(scheduler.load_schedules()))
        if command == "/edit":
            schedules = {index: schedule for index, schedule in schedules.items()
                         if schedule.get("status", "pending") == "pending"}
        show_schedules(schedules)
        if command != "/list" and schedules:
            state.update(step=command[1:], schedules=schedules)
            reply("Enter a schedule number, or /cancel.")
    elif command == "/add":
        state["step"] = "contact"
        reply("Enter the contact or WhatsApp group.")
    elif command == "/addstatus":
        state["step"] = "status_link"
        reply(STATUS_LINK_PROMPT)
    elif command == "/cancel":
        reply("Cancelled.")
    else:
        markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        markup.add(*MENU)
        reply("Use the menu or /list, /add, /addstatus, /edit, /delete to manage WhatsApp schedules.", reply_markup=markup)


def timezone_input(text):
    if text.lower() == "local":
        return None
    schedule_zone(text)
    return text


def datetime_input(text):
    try:
        return datetime.strptime(text.replace("T", " "), "%Y-%m-%d %H:%M").isoformat()
    except ValueError:
        raise ValueError("Use YYYY-MM-DD HH:MM, for example 2026-11-15 08:30.") from None


def edit_value(field, text):
    if field == "timezone":
        return timezone_input(text)
    if field == "datetime":
        return datetime_input(text)
    if field == "recurring":
        return None if text.lower() == "none" else text.lower()
    if field == "options":
        options = [item.strip() for item in text.split(",") if item.strip()]
        if len(options) < 2 or len(options) != len(set(options)):
            raise ValueError("Enter at least two unique options.")
        return options
    if field == "allow_multi_select":
        if text.lower() not in ("yes", "no"):
            raise ValueError("Enter yes or no.")
        return text.lower() == "yes"
    return text


def ask_date():
    now = datetime.now(schedule_zone(state["timezone"]))
    sent = reply(DATE_PROMPT, reply_markup=calendar.create_calendar(
        name=calendar_data.prefix, year=now.year, month=now.month
    ))
    state.update(step="date", picker=sent.message_id)


def ask_repeat(value):
    state.update(step="repeat", datetime=value)
    state.pop("picker", None)
    reply(REPEAT_PROMPT)


def handle_step(text):
    step = state["step"]
    if step == "contact":
        state.update(step="message", contact=text)
        reply("Enter the WhatsApp message.")
    elif step == "message":
        state.update(step="zone", message=text)
        reply(ZONE_PROMPT)
    elif step == "status_link":
        state.update(step="zone", link=status_link(text), audience=PHONE_STATUS_AUDIENCE)
        reply("This uses your usual WhatsApp Status audience. " + ZONE_PROMPT)
    elif step == "zone":
        state["timezone"] = timezone_input(text)
        ask_date()
    elif step == "date":
        ask_repeat(datetime_input(text))
    elif step == "repeat":
        recurring = edit_value("recurring", text)
        timing = (state["datetime"], recurring, state["timezone"])
        try:
            if "audience" in state:
                added = scheduler.add_status_schedule(state["link"], state["audience"], *timing)
            else:
                added = scheduler.add_message_schedule(state["contact"], state["message"], *timing)
        except ValueError as error:
            if "clock change" in str(error):
                reply(str(error))
                ask_date()
                return
            raise
        state.clear()
        viewers = " It will use your usual WhatsApp Status audience." if added["type"] == "status" else ""
        reply(f"Schedule added for {added['contact']} at {schedule_label(added)}.{viewers}")
    elif step in ("edit", "delete"):
        try:
            selected = state["schedules"][int(text)]
        except (ValueError, KeyError):
            raise ValueError("Enter one of the listed schedule numbers.") from None
        if step == "delete":
            removed = scheduler.remove_schedule(selected["id"], expected=schedule_revision(selected))
            state.clear()
            reply("Schedule deleted." if removed else "Schedule changed. Use /delete to reload the list.")
        else:
            content_fields = {
                "message": ["contact", "message"],
                "poll": ["contact", "question", "options", "multi"],
                "status": ["link", "viewers"],
            }
            fields = ["time", "timezone", "repeat"] + content_fields[selected["type"]]
            state.update(step="field", selected=selected, fields=fields)
            reply(f"{schedule_label(selected)}\nWhich field should change? {', '.join(fields)}")
    elif step == "field":
        name = text.lower()
        if name not in state["fields"]:
            raise ValueError("Choose " + ", ".join(state["fields"]) + ".")
        field, prompt = FIELDS[name]
        state.update(step="value", field=field)
        reply(prompt)
    elif step in ("hour", "minute"):
        ask_repeat(datetime_input(text))
    elif step == "value":
        selected = state["selected"]
        field = state["field"]
        updated = scheduler.update_schedule(
            selected["id"], {field: edit_value(field, text)}, expected=schedule_revision(selected)
        )
        state.clear()
        reply(f"Schedule updated. Next run {schedule_label(updated)}." if updated else
              "Schedule changed while you were editing. Use /edit to reload the list.")


@bot.message_handler(func=lambda message: authorized(message.chat))
def handle_message(message):
    text = message.text.strip()
    if not text:
        return
    command = MENU.get(text, text.split("@", 1)[0] if text.startswith("/") else None)
    try:
        if command or not state:
            begin(command)
        else:
            handle_step(text)
    except ValueError as error:
        reply(str(error))
    except Timeout:
        reply("The scheduler is sending a message. Try again in a moment.")


@bot.callback_query_handler(func=lambda call: True)
def handle_picker(call):
    if not call.message or not authorized(call.message.chat) or call.from_user.id != CHAT_ID:
        bot.answer_callback_query(call.id)
        return
    if call.message.message_id != state.get("picker"):
        bot.answer_callback_query(call.id, "This picker has expired.")
        return

    if call.data.startswith(calendar_data.prefix + calendar_data.sep) and state["step"] == "date":
        name, action, year, month, day = call.data.split(calendar_data.sep)
        if action != "IGNORE":
            bot.answer_callback_query(call.id)
        date = calendar.calendar_query_handler(bot=bot, call=call, name=name, action=action,
                                               year=year, month=month, day=day)
        if action == "CANCEL":
            state.clear()
            reply("Cancelled.")
        elif action == "DAY":
            state.update(step="hour", date=date.date())
            keyboard = InlineKeyboardMarkup(row_width=6)
            keyboard.add(*(InlineKeyboardButton(f"{hour:02d}:xx", callback_data=f"hour_{hour:02d}")
                           for hour in range(24)))
            sent = reply("Choose the hour.", reply_markup=keyboard)
            state["picker"] = sent.message_id
        return

    bot.answer_callback_query(call.id)
    if call.data.startswith("hour_") and state["step"] == "hour":
        hour = call.data.split("_")[1]
        keyboard = InlineKeyboardMarkup(row_width=4)
        keyboard.add(*(InlineKeyboardButton(f"{hour}:{minute:02d}", callback_data=f"min_{hour}_{minute:02d}")
                       for minute in range(0, 60, 5)))
        state["step"] = "minute"
        bot.edit_message_text("Choose the minute.", CHAT_ID, call.message.message_id, reply_markup=keyboard)
    elif call.data.startswith("min_") and state["step"] == "minute":
        _, hour, minute = call.data.split("_")
        value = f"{state['date']}T{hour}:{minute}"
        bot.edit_message_text(f"Selected {value.replace('T', ' ')}.", CHAT_ID, call.message.message_id)
        ask_repeat(value)


def run_bot():
    bot.infinity_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    run_bot()
