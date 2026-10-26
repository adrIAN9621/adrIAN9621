@echo off
REM ============================================================
REM  Carpatica Asistenta IT - pornire AGENT (angajat).
REM  Dublu-clic. Intreaba adresa serverului (alt laptop sau local).
REM ============================================================
chcp 65001 >nul
title Carpatica Asistenta IT - Agent
cd /d "%~dp0"
setlocal

REM --- gaseste un Python REAL (nu stub-ul din Microsoft Store) ---
call :findpy
if not defined PY (
  echo Python nu este instalat. Il instalez acum ^(dureaza 1-2 min^)...
  winget install -e --id Python.Python.3.12 --scope machine --accept-source-agreements --accept-package-agreements
  REM reimprospatam PATH-ul in sesiunea curenta
  set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%ProgramFiles%\Python312;%ProgramFiles%\Python312\Scripts"
  call :findpy
)
if not defined PY (
  echo Nu am gasit Python nici dupa instalare. Inchideti si redeschideti aceasta fereastra,
  echo sau instalati Python de la https://www.python.org ^(bifati "Add to PATH"^).
  pause & exit /b 1
)

echo [1/2] Instalez dependentele agentului ^(o singura data^)...
%PY% -m pip install -r agent\requirements.txt

echo.
echo Adresa IP a laptopului pe care ruleaza SERVERUL.
echo   - pe acelasi laptop ca serverul: apasati Enter ^(127.0.0.1^)
echo   - pe alt laptop: scrieti IP-ul serverului ^(ex. 192.168.1.50^)
set "SRV=127.0.0.1"
set /p SRV=IP server [127.0.0.1]:

%PY% -c "import json,io,sys;ip=sys.argv[1].strip() or '127.0.0.1';json.dump({'server_url':'ws://%%s:8443/ws/agent'%%ip,'allow_insecure':True,'verify_tls':False},io.open('agent/config.json','w',encoding='utf-8'),indent=2)" "%SRV%"

echo.
echo [2/2] Pornesc agentul catre ws://%SRV%:8443 . Va aparea o fereastra cu ID si COD.
%PY% agent\carpatica_agent.py
echo.
pause
exit /b 0

:findpy
set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY ( python -c "import sys" >nul 2>&1 && set "PY=python" )
goto :eof
