@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Citeste comenzile active din Comanda Personal (ActiveOrders) - doar citire, salvate local
python -m app.cmdpers comenzi date-reale
pause
