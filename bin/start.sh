#!/bin/sh
set -eu

python manage.py migrate --noinput
python manage.py check --deploy --fail-level WARNING
python manage.py deployment_check
# Integrity errors block startup. Recoverable operational warnings remain visible
# in the deploy log and scheduled strict audits without taking the service down.
python manage.py data_audit

exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --timeout "${GUNICORN_TIMEOUT_SECONDS:-180}" \
    --no-control-socket \
    --access-logfile - \
    --error-logfile -
