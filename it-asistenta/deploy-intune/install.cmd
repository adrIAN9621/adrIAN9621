@echo off
REM Instalare agent Carpatica Asistenta IT (rulat de Intune in context SYSTEM).
setlocal
set "DEST=%ProgramFiles%\Carpatica Asistenta IT"

if not exist "%DEST%" mkdir "%DEST%"
copy /y "%~dp0Carpatica-Asistenta-IT.exe" "%DEST%\" >nul || exit /b 1
copy /y "%~dp0config.json" "%DEST%\" >nul || exit /b 1

REM Pornire automata la logon, in sesiunea utilizatorului (fereastra cu ID + consimtamant).
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run" /v "CarpaticaAsistentaIT" /t REG_SZ /d "\"%DEST%\Carpatica-Asistenta-IT.exe\"" /f >nul

REM Scurtatura in meniul Start (ca userul sa o poata redeschide daca o inchide).
set "SM=%ProgramData%\Microsoft\Windows\Start Menu\Programs"
powershell -NoProfile -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%SM%\Carpatica Asistenta IT.lnk');" ^
  "$s.TargetPath='%DEST%\Carpatica-Asistenta-IT.exe'; $s.WorkingDirectory='%DEST%'; $s.Save()" >nul 2>&1

echo Instalat in %DEST%.
exit /b 0
