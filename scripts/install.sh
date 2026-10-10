#!/usr/bin/env bash
# Installation de LUNATIC IMSI LAB dans un environnement virtuel local (.venv).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
"$PY" -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ requis"'
"$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e . --no-deps
echo
echo "Installation terminée. Vérification :"
QT_QPA_PLATFORM=${QT_QPA_PLATFORM:-offscreen} python -m pytest -q
echo
echo "Lancer l'interface : scripts/run.sh"
echo "Récepteurs SDR (optionnel) : voir docs/equipment_guide.md"
