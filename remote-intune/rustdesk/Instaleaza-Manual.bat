@echo off
REM Pentru laptopurile care NU sunt inca in Intune.
REM Click dreapta pe acest fisier -> "Run as administrator".
chcp 65001 >nul
echo === Carpatica Remote - instalare manuala ===
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Trebuie rulat ca ADMINISTRATOR. Click dreapta -> Run as administrator.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
echo.
echo ---------------------------------------------
echo Date de conectare (ID + parola):
type "%ProgramData%\CarpaticaRemote\device-info.txt"
echo ---------------------------------------------
pause
