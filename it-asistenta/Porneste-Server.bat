@echo off
REM ============================================================
REM  Carpatica Asistenta IT - pornire SERVER (test in retea).
REM  Dublu-clic (de preferat ca Administrator, pentru firewall).
REM ============================================================
chcp 65001 >nul
title Carpatica Asistenta IT - Server
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo Python nu este instalat. Instalati-l: winget install Python.Python.3.12
  pause & exit /b 1
)

echo [1/4] Instalez dependentele serverului (o singura data)...
python -m pip install -r server\requirements.txt

echo.
echo [2/4] Creati un tehnician. Puneti o parola de minim 8 caractere.
python -m server adduser test

REM mod de test fara TLS (http/ws)
python -c "import json,io;p='server/config.json';d=json.load(io.open(p,encoding='utf-8'));d['allow_insecure']=True;d['host']='0.0.0.0';json.dump(d,io.open(p,'w',encoding='utf-8'),indent=2,ensure_ascii=False)"

echo.
echo [3/4] Deschid portul 8443 in firewall (necesita Administrator)...
netsh advfirewall firewall add rule name="Carpatica Asistenta IT 8443" dir=in action=allow protocol=TCP localport=8443 >nul 2>&1
if errorlevel 1 (echo     ^(Nu am putut adauga regula - rulati ca Administrator sau adaugati-o manual.^)) else (echo     OK)

echo.
echo [4/4] Adresa de retea a acestui server ^(pentru agentul de pe alte laptopuri^):
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do echo        ws://%%a:8443/ws/agent  ^(scoateti spatiul din fata^)
echo.
echo Consola web se deschide acum. Utilizator: test
echo Pe ALT laptop, puneti in agent adresa de mai sus ^(ws://IP:8443/ws/agent^).
echo NU inchideti aceasta fereastra cat timp folositi aplicatia.
start "" http://127.0.0.1:8443
python -m server run --host 0.0.0.0
echo.
pause
