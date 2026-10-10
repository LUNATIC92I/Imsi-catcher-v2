@echo off
cd /d "%~dp0\.."
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat
if "%~1"=="" (python -m lunatic_imsi_lab gui) else (python -m lunatic_imsi_lab %*)
