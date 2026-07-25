#!/bin/sh
set -eu

python manage.py migrate --noinput
python manage.py check --deploy --fail-level WARNING
python manage.py deployment_check
python manage.py data_audit --fail-on-warning

exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --no-control-socket \
    --access-logfile - \
    --error-logfile -
