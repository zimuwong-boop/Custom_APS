#!/bin/sh
set -eu
: "${SECRET_KEY:?Set SECRET_KEY in the container environment}"
python manage.py migrate --noinput
python manage.py init_system
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 1 --threads 4 --timeout 120 --access-logfile - --error-logfile -
