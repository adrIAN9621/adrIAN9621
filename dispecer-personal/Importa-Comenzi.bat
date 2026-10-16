@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Importa cel mai nou ComenziActive_*.xlsx din Downloads (exportat din Comanda) - totul ramane local
python -m app.comenzi_xlsx
pause
