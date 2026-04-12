@echo off
REM Pull latest code and update dependencies
"%~dp0venv\Scripts\python.exe" "%~dp0manage.py" update %*
