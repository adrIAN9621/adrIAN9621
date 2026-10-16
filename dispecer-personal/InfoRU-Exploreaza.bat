@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Raport cu structura paginii InfoRU (fara date) - trimiteti raport.md
python -m app.inforu explora date-reale
pause
