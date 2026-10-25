@echo off
REM ============================================================
REM  Carpatica Asistenta IT - pornire AGENT (angajat).
REM  Dublu-clic. Intreaba adresa serverului (alt laptop sau local).
REM ============================================================
chcp 65001 >nul
title Carpatica Asistenta IT - Agent
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo Python nu este instalat. Instalati-l: winget install Python.Python.3.12
  pause & exit /b 1
)

echo [1/2] Instalez dependentele agentului (o singura data)...
python -m pip install -r agent\requirements.txt

echo.
echo Adresa IP a laptopului pe care ruleaza SERVERUL.
echo   - pe acelasi laptop ca serverul: apasati Enter (127.0.0.1)
echo   - pe alt laptop: scrieti IP-ul serverului (ex. 192.168.1.50)
set "SRV=127.0.0.1"
set /p SRV=IP server [127.0.0.1]:

python -c "import json,io,sys;ip=sys.argv[1].strip() or '127.0.0.1';json.dump({'server_url':'ws://%%s:8443/ws/agent'%%ip,'allow_insecure':True,'verify_tls':False},io.open('agent/config.json','w',encoding='utf-8'),indent=2)" "%SRV%"

echo.
echo [2/2] Pornesc agentul catre ws://%SRV%:8443 . Va aparea o fereastra cu ID si COD.
echo     Introduceti-le in consola (tab "Asistenta") si acceptati cererea.
python agent\carpatica_agent.py
echo.
pause
