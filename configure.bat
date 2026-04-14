@echo off
REM Re-run email + Telegram notification setup
if exist "%~dp0venv\Scripts\python.exe" (
    "%~dp0venv\Scripts\python.exe" "%~dp0manage.py" configure %*
) else (
    python "%~dp0manage.py" configure %*
)
