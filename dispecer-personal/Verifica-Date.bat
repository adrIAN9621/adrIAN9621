@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Verifica datele inregistrate (InfoRU / CmdPers) din date-reale
python -m app.verifica date-reale
pause
