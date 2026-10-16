@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Cere pe rand utilizatorul si parola pentru Comanda Personal si InfoRU
rem si le salveaza local in cmdpers.json si inforu.json (nu se urca pe GitHub).
python -m app.configurare
if errorlevel 1 goto end
echo Verific logarea in Comanda Personal...
python -m app.cmdpers test
echo Verific logarea in InfoRU...
python -m app.inforu test
:end
pause
