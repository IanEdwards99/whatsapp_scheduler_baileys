@echo off
REM Stop all WhatsApp Scheduler processes
if exist "%~dp0venv\Scripts\python.exe" (
    "%~dp0venv\Scripts\python.exe" "%~dp0manage.py" stop %*
) else (
    python "%~dp0manage.py" stop %*
)
