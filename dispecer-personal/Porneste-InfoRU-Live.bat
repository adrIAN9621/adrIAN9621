@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Porneste aplicatia pe trenurile reale din InfoRU (doar citire, in umbra - nimeni nu primeste comenzi)
if not exist .venv (
  python -m venv .venv
  call .venv\Scripts\activate.bat
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)
set DISPECER_CONFIG=%~dp0config-inforu-live.json
python run.py
pause
