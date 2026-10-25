@echo off
REM ============================================================================
REM  Carpatica Asistenta IT - INSTALATOR UNIC (RustDesk + agent "cu acord")
REM  Dublu-click: Click dreapta pe acest fisier -> "Run as administrator".
REM ============================================================================
chcp 65001 >nul
echo === Carpatica Asistenta IT - instalare unica ===

net session >nul 2>&1
if %errorlevel% neq 0 (
  echo.
  echo Trebuie rulat ca ADMINISTRATOR.
  echo Click dreapta pe acest fisier -^> "Run as administrator".
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-RemoteCarpatica.ps1"
set RC=%errorlevel%

echo.
echo ---------------------------------------------
if %RC% equ 0 (
  echo Instalare finalizata cu succes.
  echo Date de conectare RustDesk ^(ID + parola^):
  type "%ProgramData%\CarpaticaRemote\device-info.txt" 2>nul
) else (
  echo Instalarea a esuat ^(cod %RC%^). Vedeti jurnalele din:
  echo   %ProgramData%\CarpaticaRemote\install-unificat.log
  echo   %ProgramData%\CarpaticaRemote\install.log
)
echo ---------------------------------------------
pause
exit /b %RC%
