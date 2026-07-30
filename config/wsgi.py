"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

from django.conf import settings
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.Settings.prod')

application = get_wsgi_application()

# Render starts through the Dockerfile's bin/start.sh, which applies migrations
# before Gunicorn. This defense-in-depth guard also checks physical model columns
# so any transient or historical schema mismatch fails closed instead of serving
# pages that return database errors.
if not settings.DEBUG:
    from core.deployment_safety import assert_schema_current

    assert_schema_current()
