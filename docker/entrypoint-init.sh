#!/bin/sh
# One-shot initialisation used by docker compose: idempotent, safe to rerun.
set -eu
sorvia migrate
sorvia bootstrap-roles
sorvia seed --if-empty --scale "${SORVIA_SEED_SCALE:-1}" ${SORVIA_DEMO_PASSWORD:+--demo-users}
sorvia index-schema
echo "Sorvia database is ready."
