@echo off
cd /d "%~dp0"
rem Cauta prin aplicatie paginile cu mecanici si activitati (doar citire)
python -m app.cmdpers explora date-reale
pause
