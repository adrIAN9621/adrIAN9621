@echo off
cd /d "%~dp0"
rem Inregistreaza pozitiile locomotivelor la fiecare minut
python -m app.cmdpers inregistreaza date-reale
pause
