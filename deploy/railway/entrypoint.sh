#!/bin/sh
set -eu
: "${SECRET_KEY:?Set a unique SECRET_KEY in Railway service variables}"
if test "${RAILWAY_VOLUME_MOUNT_PATH:-}" != /data; then
  echo 'Attach a Railway persistent volume at /data before deploying.' >&2
  exit 1
fi
python /opt/deploy/seed_database.py
python manage.py migrate --noinput
python manage.py init_system
exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers 1 --threads 4 --timeout 120 --access-logfile - --error-logfile -
