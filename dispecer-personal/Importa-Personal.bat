@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Importa cel mai nou DatePersonal_*.xls din Downloads (lista de personal cu domiciliul) - ramane local
python -m app.personal_xls
pause
