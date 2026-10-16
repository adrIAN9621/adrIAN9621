@echo off
cd /d "%~dp0"
rem Doar citire: ia pozitiile de la laptop_proxy.py (/api/locations) si le salveaza in date-reale\locatii
python inregistreaza_cmdpers.py --url http://127.0.0.1:8765/api/locations --dosar ..\date-reale --interval 60
pause
