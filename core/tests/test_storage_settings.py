from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.storage import build_media_storage, s3_media_enabled


class MediaStorageSettingsTests(SimpleTestCase):
    def test_filesystem_storage_is_the_default(self):
        environ = {}

        self.assertFalse(s3_media_enabled(environ))
        self.assertEqual(
            build_media_storage(environ),
            {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        )

    def test_s3_storage_uses_private_signed_urls(self):
        environ = {
            'USE_S3_MEDIA': 'True',
            'AWS_STORAGE_BUCKET_NAME': 'example-media',
            'AWS_S3_REGION_NAME': 'us-east-2',
        }

        self.assertTrue(s3_media_enabled(environ))
        storage = build_media_storage(environ)
        self.assertEqual(storage['BACKEND'], 'storages.backends.s3.S3Storage')
        self.assertEqual(
            storage['OPTIONS'],
            {
                'bucket_name': 'example-media',
                'region_name': 'us-east-2',
                'location': 'media',
                'default_acl': None,
                'file_overwrite': False,
                'querystring_auth': True,
                'querystring_expire': 3600,
            },
        )

    def test_s3_storage_requires_a_bucket(self):
        with self.assertRaisesMessage(
            ImproperlyConfigured,
            'AWS_STORAGE_BUCKET_NAME is empty',
        ):
            build_media_storage({'USE_S3_MEDIA': 'yes'})
