@echo off
REM ============================================================
REM  Carpatica Asistenta IT - pornire SERVER (test local).
REM  Dublu-clic. Instaleaza, creeaza un tehnician, porneste.
REM ============================================================
chcp 65001 >nul
title Carpatica Asistenta IT - Server
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo Python nu este instalat. Instalati-l: winget install Python.Python.3.12
  echo apoi deschideti din nou acest fisier.
  pause & exit /b 1
)

echo [1/3] Instalez dependentele serverului (o singura data)...
python -m pip install -r server\requirements.txt

echo.
echo [2/3] Creati un tehnician. Puneti o parola de minim 8 caractere.
python -m server adduser test

REM activeaza modul fara TLS pentru test local (http/ws)
python -c "import json,io;p='server/config.json';d=json.load(io.open(p,encoding='utf-8'));d['allow_insecure']=True;d['host']='127.0.0.1';json.dump(d,io.open(p,'w',encoding='utf-8'),indent=2,ensure_ascii=False)"

echo.
echo [3/3] Pornesc serverul. Se deschide consola in browser.
echo     Utilizator: test   (parola pusa mai sus)
echo     Nu inchideti aceasta fereastra cat timp folositi aplicatia.
start "" http://127.0.0.1:8443
python -m server
echo.
pause
