@echo off
cd /d "%~dp0"
if not exist venv\Scripts\pythonw.exe (
    echo Primero haz doble clic en instalar.bat
    pause
    exit /b 1
)
start "" venv\Scripts\pythonw.exe app_web.py
