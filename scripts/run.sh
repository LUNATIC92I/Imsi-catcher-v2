#!/usr/bin/env bash
# Lancement de LUNATIC IMSI LAB. Sans argument : interface graphique.
# Exemples : scripts/run.sh simulate --scenario synthetic_anomaly --report
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi
if [ $# -eq 0 ]; then
  exec python -m lunatic_imsi_lab gui
fi
exec python -m lunatic_imsi_lab "$@"
