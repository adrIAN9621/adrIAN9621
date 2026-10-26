@echo off
REM Dezinstalare agent Carpatica Asistenta IT.
setlocal
set "DEST=%ProgramFiles%\Carpatica Asistenta IT"
reg delete "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run" /v "CarpaticaAsistentaIT" /f >nul 2>&1
del "%ProgramData%\Microsoft\Windows\Start Menu\Programs\Carpatica Asistenta IT.lnk" >nul 2>&1
taskkill /f /im "Carpatica-Asistenta-IT.exe" >nul 2>&1
if exist "%DEST%" rmdir /s /q "%DEST%"
exit /b 0
