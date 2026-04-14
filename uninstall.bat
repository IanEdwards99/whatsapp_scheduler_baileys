@echo off
REM Uninstall WhatsApp Scheduler (removes deps + session; keeps schedules unless you confirm)
if exist "%~dp0venv\Scripts\python.exe" (
    "%~dp0venv\Scripts\python.exe" "%~dp0manage.py" uninstall %*
) else (
    python "%~dp0manage.py" uninstall %*
)
