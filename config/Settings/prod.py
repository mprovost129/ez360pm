import os

from config.storage import build_media_storage, s3_media_enabled

from .base import *  # noqa: F403

DEBUG = False

ALLOWED_HOSTS = [value.strip() for value in os.environ['ALLOWED_HOSTS'].split(',') if value.strip()]

# Whitenoise — insert after SecurityMiddleware
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')  # noqa: F405

USE_S3_MEDIA = s3_media_enabled(os.environ)

STORAGES = {
    'default': build_media_storage(os.environ),
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

# Persistent DB connections belong to the database configuration itself.
DATABASES['default']['CONN_MAX_AGE'] = int(os.environ.get('DB_CONN_MAX_AGE', '60'))  # noqa: F405
DATABASES['default']['CONN_HEALTH_CHECKS'] = True  # noqa: F405

CSRF_TRUSTED_ORIGINS = [
    value.strip()
    for value in os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',')
    if value.strip()
]

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/1'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        },
    }
}

# HTTPS / security
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
