@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Verifica logarea in InfoRU si cate trenuri vede
python -m app.inforu test date-reale
pause
