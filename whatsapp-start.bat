@echo off
REM Start WhatsApp driver + scheduler
"%~dp0venv\Scripts\python.exe" "%~dp0manage.py" start %*
