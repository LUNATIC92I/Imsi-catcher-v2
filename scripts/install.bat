@echo off
REM Installation de LUNATIC IMSI LAB (Windows) dans .venv
cd /d "%~dp0\.."
py -3.12 -m venv .venv || python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e . --no-deps
python -m pytest -q
echo Lancer l'interface : scripts\run.bat
