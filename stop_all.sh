#!/bin/bash
# Stop all services

echo "Stopping all services..."

pkill -f "node server.js"
pkill -f "background_scheduler.py"
pkill -f "app.py"

echo "All services stopped"
