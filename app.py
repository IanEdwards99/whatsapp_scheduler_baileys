from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from scheduler_core import MessageScheduler
from message_history import MessageHistory
import requests
from requests.exceptions import RequestException
import subprocess
import os
import time
from dotenv import load_dotenv
load_dotenv()

import os
import signal

app = Flask(__name__)
app.secret_key = "your_secret_key_change_in_production"
scheduler = MessageScheduler("schedules/schedule.json")
history = MessageHistory()  # Add history tracking

DRIVER_SERVER_URL = os.environ.get("DRIVER_URL", "http://127.0.0.1:5002")


def ensure_driver_server():
    """Ensure driver server is running"""
    try:
        r = requests.get(f"{DRIVER_SERVER_URL}/status", timeout=2)
        if r.status_code == 200:
            return True
    except Exception:
        pass
    return False


@app.route("/")
def index():
    schedules = scheduler.load_schedules()
    return render_template("index.html", schedules=schedules, enumerate=enumerate)

@app.route("/add", methods=["GET", "POST"])
def add_schedule():
    if request.method == "POST":
        schedule_type = request.form.get("type")
        contact = request.form.get("contact")
        datetime_str = request.form.get("datetime")  # New: full datetime
        recurring = request.form.get("recurring")
        
        if schedule_type == "message":
            message = request.form.get("message")
            if not contact or not message or not datetime_str:
                flash("Please provide contact, message, and date/time.", "error")
                return redirect(url_for("add_schedule"))
            scheduler.add_message_schedule(contact, message, datetime_str, recurring)
            flash("Message schedule added successfully!", "success")
        
        elif schedule_type == "poll":
            question = request.form.get("question")
            options = request.form.get("options").split(",")
            options = [opt.strip() for opt in options if opt.strip()]
            allow_multi_select = request.form.get("allow_multi_select") == "on"
            
            if not contact or not question or not options or not datetime_str:
                flash("Please provide contact, question, options, and date/time.", "error")
                return redirect(url_for("add_schedule"))
            
            if len(options) != len(set(options)):
                flash("Poll options must be unique.", "error")
                return redirect(url_for("add_schedule"))
            
            scheduler.add_poll_schedule(contact, question, options, datetime_str, recurring, allow_multi_select)
            flash("Poll schedule added successfully!", "success")
        
        return redirect(url_for("index"))
    
    return render_template("add_schedule.html")


@app.route("/edit/<int:index>", methods=["GET", "POST"])
def edit_schedule(index):
    schedules = scheduler.load_schedules()
    
    if index < 0 or index >= len(schedules):
        flash("Invalid schedule index.", "error")
        return redirect(url_for("index"))
    
    schedule = schedules[index]
    
    if request.method == "POST":
        schedule_type = request.form.get("type")
        contact = request.form.get("contact")
        datetime_str = request.form.get("datetime")
        recurring = request.form.get("recurring")
        
        if schedule_type == "message":
            message = request.form.get("message")
            if not contact or not message or not datetime_str:
                flash("Please provide contact, message, and date/time.", "error")
                return redirect(url_for("edit_schedule", index=index))
            
            scheduler.update_schedule(index, {
                'type': 'message',
                'contact': contact,
                'message': message,
                'datetime': datetime_str,
                'recurring': recurring
            })
            flash("Schedule updated successfully!", "success")
        
        elif schedule_type == "poll":
            question = request.form.get("question")
            options = request.form.get("options").split(",")
            options = [opt.strip() for opt in options if opt.strip()]
            allow_multi_select = request.form.get("allow_multi_select") == "on"
            
            if not contact or not question or not options or not datetime_str:
                flash("Please provide contact, question, options, and date/time.", "error")
                return redirect(url_for("edit_schedule", index=index))
            
            if len(options) != len(set(options)):
                flash("Poll options must be unique.", "error")
                return redirect(url_for("edit_schedule", index=index))
            
            scheduler.update_schedule(index, {
                'type': 'poll',
                'contact': contact,
                'question': question,
                'options': options,
                'datetime': datetime_str,
                'recurring': recurring,
                'allow_multi_select': allow_multi_select
            })
            flash("Schedule updated successfully!", "success")
        
        return redirect(url_for("index"))
    
    # GET request - show edit form with pre-filled data
    # Convert next_run to datetime-local format for the input
    next_run = schedule.get('next_run', '')
    if 'T' in str(next_run):
        datetime_value = next_run[:16]  # YYYY-MM-DDTHH:MM
    else:
        # If only time, use today's date
        from datetime import datetime as dt
        datetime_value = dt.now().strftime("%Y-%m-%d") + "T" + schedule.get('time', '00:00')
    
    return render_template("edit_schedule.html", schedule=schedule, index=index, datetime_value=datetime_value)


@app.route("/delete/<int:index>")
def delete_schedule(index):
    removed = scheduler.remove_schedule(index)
    if removed:
        flash("Schedule deleted successfully!", "success")
    else:
        flash("Invalid schedule index.", "error")
    return redirect(url_for("index"))


@app.route("/send_now", methods=["GET", "POST"])
def send_now():
    if request.method == "POST":
        if not ensure_driver_server():
            flash("Driver server not ready. Please ensure server.js is running.", "error")
            return redirect(url_for("send_now"))
        
        schedule_type = request.form.get("type")
        contact = request.form.get("contact")
        
        try:
            if schedule_type == "message":
                message = request.form.get("message")
                if not contact or not message:
                    flash("Please provide contact and message.", "error")
                    return redirect(url_for("send_now"))
                
                success, error_detail = scheduler.send_message_via_api(contact, message)
                
                # Log to history
                history.add_entry(
                    entry_type='message',
                    contact=contact,
                    content={'message': message},
                    status='sent' if success else 'failed',
                    metadata={'source': 'manual', **({"error": error_detail} if error_detail else {})}
                )
                
                if success:
                    flash("Message sent successfully!", "success")
                else:
                    flash(f"Failed to send message: {error_detail}", "error")
            
            elif schedule_type == "poll":
                question = request.form.get("question")
                options = request.form.get("options").split(",")
                options = [opt.strip() for opt in options if opt.strip()]
                allow_multi_select = request.form.get("allow_multi_select") == "on"
                
                if not contact or not question or not options:
                    flash("Please provide contact, question, and options.", "error")
                    return redirect(url_for("send_now"))
                
                if len(options) != len(set(options)):
                    flash("Poll options must be unique.", "error")
                    return redirect(url_for("send_now"))
                
                success, error_detail = scheduler.send_poll_via_api(contact, question, options, allow_multi_select)
                
                # Log to history
                history.add_entry(
                    entry_type='poll',
                    contact=contact,
                    content={'question': question, 'options': options, 'allow_multi_select': allow_multi_select},
                    status='sent' if success else 'failed',
                    metadata={'source': 'manual', **({"error": error_detail} if error_detail else {})}
                )
                
                if success:
                    flash("Poll sent successfully!", "success")
                else:
                    flash(f"Failed to send poll: {error_detail}", "error")
        
        except Exception as e:
            flash(f"Error: {e}", "error")
        
        return redirect(url_for("index"))
    
    return render_template("send_now.html")


@app.route("/overview")
def overview():
    schedules = scheduler.load_schedules()
    return render_template("overview.html", schedules=schedules)


@app.route("/history")
def view_history():
    """View message history"""
    recent = history.get_recent(100)
    stats = history.get_stats()
    return render_template("history.html", history=recent, stats=stats)



@app.route("/shutdown", methods=["POST"])
def shutdown():
    """Shutdown the Flask server"""
    try:
        scheduler.stop()
    except:
        pass
    os.kill(os.getpid(), signal.SIGINT)
    return "Server is shutting down..."

@app.route("/api/status")
def api_status():
    """API endpoint for health check"""
    driver_ok = ensure_driver_server()
    return jsonify({
        "flask": "ok",
        "driver": "ok" if driver_ok else "down"
    })

import os

if __name__ == "__main__":
    # Use debug mode only in development (set FLASK_DEBUG=1 to enable)
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host="0.0.0.0", port=5000, debug=debug_mode)
