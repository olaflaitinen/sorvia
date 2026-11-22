#!/usr/bin/env bash
# Vercel build step.
#   1. Initialise the database when DATABASE_URL is available (idempotent):
#      migrations, login roles, seed data (only if empty), semantic layer.
#   2. Build the web client into web/dist.
set -euo pipefail

if [ -n "${DATABASE_URL:-${POSTGRES_URL:-}}" ]; then
  echo "==> Initialising database"
  PY=$(command -v python3 || command -v python)
  "$PY" -m pip install --quiet --disable-pip-version-check -r requirements.txt \
    || "$PY" -m pip install --quiet --disable-pip-version-check --break-system-packages -r requirements.txt
  export PYTHONPATH="$PWD/src"
  "$PY" -m sorvia.cli migrate
  "$PY" -m sorvia.cli bootstrap-roles
  "$PY" -m sorvia.cli seed --if-empty --scale "${SORVIA_SEED_SCALE:-1}" ${SORVIA_DEMO_PASSWORD:+--demo-users}
  "$PY" -m sorvia.cli index-schema
else
  echo "==> DATABASE_URL is not set; skipping database initialisation"
fi

echo "==> Building web client"
npm run build --prefix web
