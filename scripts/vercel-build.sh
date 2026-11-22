#!/usr/bin/env bash
# Vercel build step.
#   1. Initialise the database when a Postgres URL is available (idempotent):
#      migrations, login roles, seed data (only if empty), semantic layer.
#   2. Build the web client into web/dist.
set -euo pipefail

pick_python() {
  for candidate in python3.13 python3.12 python3; do
    if command -v "$candidate" >/dev/null 2>&1 \
       && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

if [ -n "${DATABASE_URL:-${POSTGRES_URL:-}}" ]; then
  echo "==> Initialising database"
  VENV=/tmp/sorvia-build-venv
  if PY=$(pick_python); then
    "$PY" -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --disable-pip-version-check -r requirements.txt
  else
    echo "    Python 3.12+ not found; provisioning it with uv"
    command -v uv >/dev/null 2>&1 || { curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"; }
    uv venv --python 3.12 "$VENV"
    uv pip install --python "$VENV/bin/python" --quiet -r requirements.txt
  fi
  export PYTHONPATH="$PWD/src"
  SV="$VENV/bin/python -m sorvia.cli"
  $SV migrate
  $SV bootstrap-roles
  $SV seed --if-empty --scale "${SORVIA_SEED_SCALE:-1}" --demo-users
  $SV index-schema
else
  echo "==> No DATABASE_URL or POSTGRES_URL; skipping database initialisation"
fi

echo "==> Building web client"
npm run build --prefix web
