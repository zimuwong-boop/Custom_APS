#!/bin/sh
set -eu
python /opt/deploy/seed_database.py
exec /app/scripts/container_entrypoint.sh
