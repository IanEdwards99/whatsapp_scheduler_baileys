import os
import datetime
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telebot_calendar import Calendar, CallbackData, ENGLISH_LANGUAGE
from dotenv import load_dotenv
from scheduler_core import MessageScheduler

# Initialize Calendar
calendar = Calendar(ENGLISH_LANGUAGE)
calendar_1 = CallbackData("calendar_1", "action", "year", "month", "day")

# Load variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("No TELEGRAM_TOKEN found in environment variables.")

bot = telebot.TeleBot(TOKEN)
scheduler = MessageScheduler("schedules/schedule.json")

user_data = {}

def send_welcome_action(message, show_help_text=False):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton('📝 List Schedules'), KeyboardButton('➕ Add Schedule'))
    markup.add(KeyboardButton('🗑 Delete Schedule'), KeyboardButton('❓ Help'))
    
    help_text = (
        "🤖 *WhatsApp Scheduler Bot*\n\n"
        "Please use the menu buttons below to manage your schedules.\n"
        "If you don't see the buttons, tap the menu icon (🎛) next to the input field."
    )
    
    if show_help_text:
        help_text = "I didn't understand that. 😅\n\n" + help_text
        
    bot.reply_to(message, help_text, reply_markup=markup, parse_mode="Markdown")

def list_schedules_action(message):
    schedules = scheduler.load_schedules()
    if not schedules:
        bot.reply_to(message, "📭 No schedules found.")
        return
        
    response = "🗓 *Current Schedules:*\n\n"
    for i, s in enumerate(schedules):
        status = "✅" if s.get('status') == 'completed' else "⏳"
        date_str = s.get('next_run') or s.get('time')
        contact = s.get('contact')
        msg = s.get('message') or s.get('question')
        sched_type = s.get('type', 'Unknown')
        
        preview = msg[:30] + '...' if msg and len(msg) > 30 else msg
        response += f"*{i}*. {status} {date_str} -> {contact}\n"
        response += f"   Type: _{sched_type}_ | \"{preview}\"\n\n"
        
    # Send long messages in chunks if necessary (Telegram limit is 4096)
    if len(response) > 4000:
        for x in range(0, len(response), 4000):
            bot.reply_to(message, response[x:x+4000], parse_mode="Markdown")
    else:
        bot.reply_to(message, response, parse_mode="Markdown")

def start_add_schedule(message):
    msg = bot.reply_to(message, "Let's add a schedule! First, who is the contact? (e.g. John Doe)")
    bot.register_next_step_handler(msg, process_contact_step)

def process_contact_step(message):
    if is_command_or_menu(message): return
    user_data[message.chat.id] = {'contact': message.text}
    msg = bot.reply_to(message, "Great! Now, what is the message text?")
    bot.register_next_step_handler(msg, process_message_step)

def process_message_step(message):
    if is_command_or_menu(message): return
    user_data[message.chat.id]['message'] = message.text
    
    now = datetime.datetime.now()
    bot.send_message(
        message.chat.id,
        "Got it. Please select a date:",
        reply_markup=calendar.create_calendar(
            name=calendar_1.prefix,
            year=now.year,
            month=now.month,
        ),
    )

def get_hour_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=6)
    buttons = []
    for h in range(24):
        buttons.append(InlineKeyboardButton(f"{h:02d}:xx", callback_data=f"hour_{h:02d}"))
    keyboard.add(*buttons)
    return keyboard

def get_minute_keyboard(hour):
    keyboard = InlineKeyboardMarkup(row_width=4)
    buttons = []
    for m in range(0, 60, 5):
        buttons.append(InlineKeyboardButton(f"{hour}:{m:02d}", callback_data=f"min_{hour}_{m:02d}"))
    keyboard.add(*buttons)
    return keyboard

def process_datetime_step(message):
    # Fallback in case they typed the time manually instead of using the inline keyboard
    if is_command_or_menu(message): return
    user_data[message.chat.id]['datetime'] = message.text
    msg = bot.reply_to(message, "Should it be recurring? (Options: daily, weekly, monthly. Or 'none' for no)")
    bot.register_next_step_handler(msg, process_recurring_step)

def process_recurring_step(message):
    if is_command_or_menu(message): return
    recurring = message.text.lower()
    if recurring == 'none':
        recurring = None
        
    data = user_data.get(message.chat.id, {})
    contact = data.get('contact')
    msg_text = data.get('message')
    datetime_str = data.get('datetime')
    
    try:
        scheduler.add_message_schedule(contact, msg_text, datetime_str, recurring)
        bot.reply_to(message, f"✅ Schedule added for *{contact}* at `{datetime_str}`", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Failed to add schedule: {e}")

def start_delete_schedule(message):
    schedules = scheduler.load_schedules()
    if not schedules:
        bot.reply_to(message, "📭 No schedules found to delete.")
        return
    
    list_schedules_action(message)
    msg = bot.reply_to(message, "Enter the index of the schedule you want to delete:")
    bot.register_next_step_handler(msg, process_delete_step)

def process_delete_step(message):
    if is_command_or_menu(message): return
    try:
        index = int(message.text.strip())
        schedules = scheduler.load_schedules()
        if 0 <= index < len(schedules):
            removed = scheduler.remove_schedule(index)
            bot.reply_to(message, f"🗑 Deleted schedule for: {removed.get('contact')}")
        else:
            bot.reply_to(message, "❌ Invalid index.")
    except ValueError:
        bot.reply_to(message, "❌ Please enter a valid number.")
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

def is_command_or_menu(message):
    """Check if the user typed a menu option or command, and route accordingly."""
    if getattr(message, 'text', None) is None:
         return False
    text = message.text
    if text in ['📝 List Schedules', '➕ Add Schedule', '🗑 Delete Schedule', '❓ Help', '/start', '/help', '/list', '/add', '/delete']:
        handle_all(message)
        return True
    if text.startswith('/'):
        handle_all(message)
        return True
    return False

@bot.callback_query_handler(func=lambda call: call.data.startswith(calendar_1.prefix))
def callback_inline(call: telebot.types.CallbackQuery):
    name, action, year, month, day = call.data.split(calendar_1.sep)
    date = calendar.calendar_query_handler(
        bot=bot, call=call, name=name, action=action, year=year, month=month, day=day
    )
    if action == "CANCEL":
        bot.send_message(call.from_user.id, "Date selection cancelled. Please type '➕ Add Schedule' to start over.")
        return
        
    if action == "DAY":
        user_data[call.from_user.id]['date'] = date.strftime('%Y-%m-%d')
        bot.send_message(
            call.from_user.id,
            f"Date selected: {date.strftime('%Y-%m-%d')}. Now, select the hour:",
            reply_markup=get_hour_keyboard()
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith("hour_"))
def callback_hour(call: telebot.types.CallbackQuery):
    hour = call.data.split('_')[1]
    bot.edit_message_text(
        chat_id=call.from_user.id,
        message_id=call.message.message_id,
        text=f"Hour selected: {hour}:xx. Now, select the minute:",
        reply_markup=get_minute_keyboard(hour)
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("min_"))
def callback_minute(call: telebot.types.CallbackQuery):
    _, hour, minute = call.data.split('_')
    datetime_str = f"{user_data[call.from_user.id]['date']}T{hour}:{minute}"
    user_data[call.from_user.id]['datetime'] = datetime_str
    
    bot.edit_message_text(
        chat_id=call.from_user.id,
        message_id=call.message.message_id,
        text=f"Time selected: {datetime_str}"
    )
    
    msg = bot.send_message(
        call.from_user.id,
        "Should it be recurring? (Options: daily, weekly, monthly. Or 'none' for no)"
    )
    bot.register_next_step_handler(msg, process_recurring_step)

@bot.message_handler(func=lambda message: True)
def handle_all(message):
    if not message.text:
         send_welcome_action(message, show_help_text=True)
         return
         
    text = message.text
    if text == '📝 List Schedules' or text == '/list':
        list_schedules_action(message)
    elif text == '➕ Add Schedule' or text == '/add':
        start_add_schedule(message)
    elif text == '🗑 Delete Schedule' or text == '/delete':
        start_delete_schedule(message)
    elif text == '❓ Help' or text in ['/start', '/help']:
        send_welcome_action(message, show_help_text=False)
    else:
        # Fallback for ANY unrecognized input
        send_welcome_action(message, show_help_text=True)

def run_bot():
    print("🤖 Telegram bot is polling...")
    try:
        bot.infinity_polling()
    except Exception as e:
        print(f"Telegram bot error: {e}")

if __name__ == '__main__':
    run_bot()
