#!/usr/bin/env bash
# Paladin — démarrage en une commande (Linux/macOS).
# Première fois : crée l'environnement Python (.venv) et installe les dépendances.
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
if [ ! -x "$PY" ]; then
  echo "Première installation : création de l'environnement Python dans .venv ..."
  PYTHON=$(command -v python3.14 || command -v python3 || command -v python) || {
    echo "Python 3.12+ introuvable : installer Python 3.14 puis relancer."; exit 1; }
  "$PYTHON" -m venv .venv
fi
"$PY" -m pip install --disable-pip-version-check -q -r requirements.lock
"$PY" -m pip install --disable-pip-version-check -q --no-deps -e .
exec "$PY" -m paladin "$@"
