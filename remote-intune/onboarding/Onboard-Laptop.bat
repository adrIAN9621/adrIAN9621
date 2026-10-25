@echo off
REM ============================================================
REM  Onboarding laptop Carpatica Feroviar.
REM  Click dreapta -> "Run as administrator".
REM ============================================================
chcp 65001 >nul
title Onboarding laptop Carpatica Feroviar

REM verifica drepturi de administrator
net session >nul 2>&1
if errorlevel 1 (
  echo Trebuie rulat ca ADMINISTRATOR.
  echo Click dreapta pe acest fisier -^> Run as administrator.
  pause & exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Onboard-Laptop.ps1"
echo.
pause
