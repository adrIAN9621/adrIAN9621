@echo off
REM Creeaza DOAR instalatorul, folosind dist\PDF-Studio.exe deja construit.
REM Util daca ai rulat deja FABRICA-INSTALATORUL.bat si ti-a lipsit doar Inno Setup.
chcp 65001 >nul
cd /d "%~dp0"

if not exist "dist\PDF-Studio.exe" (
  echo Nu exista dist\PDF-Studio.exe. Rulati intai FABRICA-INSTALATORUL.bat.
  pause & exit /b 1
)

set "ISCC="
for %%P in (
  "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
  "%ProgramFiles%\Inno Setup 6\ISCC.exe"
  "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
) do if not defined ISCC if exist "%%~P" set "ISCC=%%~P"
if not defined ISCC for /f "delims=" %%F in ('where /r "%ProgramFiles(x86)%" ISCC.exe 2^>nul') do if not defined ISCC set "ISCC=%%F"
if not defined ISCC for /f "delims=" %%F in ('where /r "%ProgramFiles%" ISCC.exe 2^>nul') do if not defined ISCC set "ISCC=%%F"

if not defined ISCC (
  echo Inno Setup nu este instalat. Instalati-l o data ^(gratuit^):
  echo    https://jrsoftware.org/isdl.php
  echo apoi rulati din nou acest fisier.
  pause & exit /b 1
)

"%ISCC%" "installer\pdfstudio.iss"
echo.
echo GATA! Instalatorul este:  %cd%\installer\Output\PDF-Studio-Setup.exe
explorer "%cd%\installer\Output"
pause
