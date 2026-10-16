@echo off
cd /d "%~dp0"
rem Salveaza local tabelele cu mecanici
python -m app.cmdpers mecanici date-reale
pause
