#!/bin/bash
# Start all services for testing

echo "=== Starting WhatsApp Scheduler System ==="

# Create logs directory if it doesn't exist
mkdir -p logs

# Start driver server in background
echo "Starting driver server..."
node server.js > logs/driver.log 2>&1 &
DRIVER_PID=$!
echo "Driver PID: $DRIVER_PID"

sleep 10

# Start background scheduler
echo "Starting background scheduler..."
python3 background_scheduler.py > logs/scheduler.log 2>&1 &
SCHEDULER_PID=$!
echo "Scheduler PID: $SCHEDULER_PID"

sleep 2

# Start Flask app
echo "Starting Flask app..."
python3 app.py > logs/flask.log 2>&1 &
FLASK_PID=$!
echo "Flask PID: $FLASK_PID"

echo ""
echo "All services started!"
echo "Driver PID: $DRIVER_PID"
echo "Scheduler PID: $SCHEDULER_PID"
echo "Flask PID: $FLASK_PID"
echo ""
echo "Access Flask app at: http://localhost:5000"
echo ""
echo "To stop all services, run: ./stop_all.sh"
echo "or manually: kill $DRIVER_PID $SCHEDULER_PID $FLASK_PID"
