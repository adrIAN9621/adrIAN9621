@echo off
cd /d "%~dp0"
rem Verifica logarea pe ambele servere
python -m app.cmdpers test date-reale
pause
