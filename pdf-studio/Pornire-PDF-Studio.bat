@echo off
REM ============================================================
REM  PDF Studio - pornire + actualizare automata la ultima versiune.
REM  Dublu-clic pe acest fisier. Nu trebuie PowerShell, nimic.
REM ============================================================
chcp 65001 >nul
title PDF Studio - Carpatica Feroviar
setlocal

set "APP=%USERPROFILE%\PDF-Studio-app"
set "ZIP=%TEMP%\pdfstudio-latest.zip"

echo Opresc versiunile vechi care ar putea rula...
taskkill /F /IM python.exe  >nul 2>&1
taskkill /F /IM pythonw.exe >nul 2>&1

echo Descarc ultima versiune...
powershell -NoProfile -Command ^
  "$ErrorActionPreference='Stop';" ^
  "Invoke-WebRequest 'https://codeload.github.com/adrIAN9621/adrIAN9621/zip/refs/heads/main' -OutFile '%ZIP%';" ^
  "if (Test-Path '%APP%') { Remove-Item '%APP%' -Recurse -Force }" ^
  "Expand-Archive '%ZIP%' -DestinationPath '%APP%' -Force"
if errorlevel 1 (
  echo Nu am putut descarca actualizarea. Verificati conexiunea la internet.
  pause & exit /b 1
)

cd /d "%APP%\adrIAN9621-main\pdf-studio"

REM Instaleaza dependentele o singura data (in Python-ul de sistem).
python -c "import fastapi,fitz,pyhanko" 1>nul 2>nul
if errorlevel 1 (
  echo Prima pornire: instalez componentele necesare (dureaza 1-3 min)...
  python -m pip install --upgrade pip >nul
  python -m pip install -r requirements.txt
)

echo Pornesc PDF Studio...
python desktop.py
