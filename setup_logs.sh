#!/bin/bash
# Setup logs directory

echo "Setting up logs directory..."
mkdir -p logs
touch logs/driver.log logs/scheduler.log logs/flask.log
echo "Logs directory created"
echo "Log files:"
echo "  - logs/driver.log"
echo "  - logs/scheduler.log"
echo "  - logs/flask.log"
