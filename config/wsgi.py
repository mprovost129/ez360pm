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

# Render should start through bin/start.sh, which applies migrations before
# Gunicorn. This guard makes an accidental Start Command override fail closed
# instead of serving code against an older schema and returning 500s.
if not settings.DEBUG:
    from core.deployment_safety import assert_schema_current

    assert_schema_current()
