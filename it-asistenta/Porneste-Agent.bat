@echo off
REM ============================================================
REM  Carpatica Asistenta IT - pornire AGENT (angajat), test local.
REM  Dublu-clic. Se conecteaza la serverul de pe acelasi PC.
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

REM config pentru test local (acelasi PC ca serverul)
python -c "import json,io;json.dump({'server_url':'ws://127.0.0.1:8443/ws/agent','allow_insecure':True,'verify_tls':False},io.open('agent/config.json','w',encoding='utf-8'),indent=2)"

echo.
echo [2/2] Pornesc agentul. Va aparea o fereastra cu ID si COD.
echo     Introduceti-le in consola (tab "Asistenta") si acceptati cererea.
python agent\carpatica_agent.py
echo.
pause
