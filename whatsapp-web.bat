@echo off
REM Start Flask web UI (on-demand, press Ctrl+C to stop)
"%~dp0venv\Scripts\python.exe" "%~dp0manage.py" web %*
