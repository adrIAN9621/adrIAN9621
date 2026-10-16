@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Descarca o data coordonatele tuturor statiilor si haltelor din Romania (OpenStreetMap) in statii.json
python -m app.statii descarca
pause
