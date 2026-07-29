#!/bin/sh
set -eu

python manage.py migrate --noinput
python manage.py check --deploy --fail-level "${DJANGO_DEPLOY_CHECK_FAIL_LEVEL:-ERROR}"
python manage.py deployment_check
# Integrity errors block startup. Recoverable operational warnings remain visible
# in the deploy log and scheduled strict audits without taking the service down.
python manage.py data_audit

# Resolve the timeout from Django's defensively parsed setting rather than passing
# the raw environment value. This keeps Gunicorn aligned with the AI timeout checks
# and safely falls back when an optional environment value is malformed.
GUNICORN_TIMEOUT_RESOLVED="$(python - <<'PY'
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.Settings.prod")
import django
django.setup()
from django.conf import settings
print(settings.GUNICORN_TIMEOUT_SECONDS)
PY
)"

exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --timeout "${GUNICORN_TIMEOUT_RESOLVED}" \
    --no-control-socket \
    --access-logfile - \
    --error-logfile -
