from collections.abc import Mapping

from django.core.exceptions import ImproperlyConfigured

TRUE_VALUES = frozenset({'1', 'true', 'yes', 'on'})


def s3_media_enabled(environ: Mapping[str, str]) -> bool:
    return environ.get('USE_S3_MEDIA', '').strip().lower() in TRUE_VALUES


def build_media_storage(environ: Mapping[str, str]) -> dict:
    if not s3_media_enabled(environ):
        return {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        }

    bucket_name = environ.get('AWS_STORAGE_BUCKET_NAME', '').strip()
    if not bucket_name:
        raise ImproperlyConfigured(
            'USE_S3_MEDIA is enabled but AWS_STORAGE_BUCKET_NAME is empty.'
        )

    region_name = environ.get('AWS_S3_REGION_NAME', 'us-east-1').strip()
    if not region_name:
        region_name = 'us-east-1'

    return {
        'BACKEND': 'storages.backends.s3.S3Storage',
        'OPTIONS': {
            'bucket_name': bucket_name,
            'region_name': region_name,
            'location': 'media',
            'default_acl': None,
            'file_overwrite': False,
            'querystring_auth': True,
            'querystring_expire': 3600,
        },
    }
