@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Salveaza trenurile in circulatie la fiecare 2 minute
python -m app.inforu inregistreaza date-reale
pause
