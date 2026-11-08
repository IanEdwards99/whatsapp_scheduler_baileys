import os
import secrets
import signal

import requests
from dotenv import load_dotenv
from filelock import Timeout
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for

from message_history import MessageHistory
from scheduler_core import MessageScheduler, schedule_datetime, schedule_label, schedule_revision

load_dotenv()
app = Flask(__name__)
app.secret_key = secrets.token_bytes(32)
app.config["TRUSTED_HOSTS"] = ["localhost", "127.0.0.1", "[::1]"]
app.jinja_env.globals.update(schedule_label=schedule_label, schedule_revision=schedule_revision)
scheduler = MessageScheduler()
history = MessageHistory()


@app.context_processor
def form_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return {"csrf_token": session["csrf"]}


@app.before_request
def validate_form_token():
    if request.method == "POST":
        token = request.form.get("csrf", "")
        if not token.isascii() or not secrets.compare_digest(token, session.get("csrf", "-")):
            abort(400, "Invalid form token. Reload the page and try again.")


@app.errorhandler(Timeout)
def queue_busy(_error):
    return "The scheduler is sending a message. Try again in a moment.", 503


DRIVER_SERVER_URL = os.environ.get("DRIVER_URL", "http://127.0.0.1:5001")


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

def schedule_form_data():
    schedule_type = request.form.get("type")
    contact = request.form.get("contact", "").strip()
    date = request.form.get("datetime", "")
    if not contact or not date:
        raise ValueError("Provide a contact and date/time.")
    data = {
        "type": schedule_type, "contact": contact, "datetime": date,
        "recurring": request.form.get("recurring"), "timezone": request.form.get("timezone"),
    }
    if schedule_type == "message":
        message = request.form.get("message", "")
        if not message.strip():
            raise ValueError("Provide a message.")
        data["message"] = message
    elif schedule_type == "poll":
        question = request.form.get("question", "").strip()
        options = [option.strip() for option in request.form.get("options", "").split(",") if option.strip()]
        if not question or len(options) < 2 or len(set(options)) != len(options):
            raise ValueError("Provide a question and at least two unique poll options.")
        data.update(question=question, options=options,
                    allow_multi_select=request.form.get("allow_multi_select") == "on")
    else:
        raise ValueError("Choose a message or poll.")
    return data


@app.route("/add", methods=["GET", "POST"])
def add_schedule():
    if request.method == "POST":
        try:
            data = schedule_form_data()
            if data["type"] == "message":
                scheduler.add_message_schedule(data["contact"], data["message"], data["datetime"],
                                               data["recurring"], data["timezone"])
            else:
                scheduler.add_poll_schedule(data["contact"], data["question"], data["options"],
                                            data["datetime"], data["recurring"],
                                            data["allow_multi_select"], data["timezone"])
        except ValueError as error:
            flash(str(error), "error")
            return render_template("add_schedule.html"), 400
        flash("Schedule added successfully!", "success")
        return redirect(url_for("index"))
    return render_template("add_schedule.html")


@app.route("/edit/<key>", methods=["GET", "POST"])
def edit_schedule(key):
    schedules = scheduler.load_schedules()
    if key.isdecimal() and len(key) < 10 and int(key) < len(schedules):
        key = schedules[int(key)]["id"]
    schedule = next((item for item in schedules if item["id"] == key), None)
    if schedule is None:
        abort(404)

    if request.method == "POST":
        try:
            data = schedule_form_data()
            updated = scheduler.update_schedule(key, data, expected=request.form.get("revision", ""))
            if updated is None:
                flash("The schedule changed. Review the latest values and try again.", "error")
                return redirect(url_for("edit_schedule", key=key))
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("edit_schedule", key=key))
        flash("Schedule updated successfully!", "success")
        return redirect(url_for("index"))

    try:
        date = schedule_datetime(schedule).strftime("%Y-%m-%dT%H:%M")
    except (KeyError, TypeError, ValueError):
        date = ""
    return render_template("edit_schedule.html", schedule=schedule, datetime_value=date)


@app.post("/delete/<key>")
def delete_schedule(key):
    removed = scheduler.remove_schedule(key, expected=request.form.get("revision", ""))
    flash("Schedule deleted successfully!" if removed else "The schedule changed. Review it and try again.",
          "success" if removed else "error")
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
                options = request.form.get("options", "").split(",")
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

if __name__ == "__main__":
    # Use debug mode only in development (set FLASK_DEBUG=1 to enable)
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host="127.0.0.1", port=5000, debug=debug_mode)
