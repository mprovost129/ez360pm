from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import ProjectFormUpload


@receiver(post_delete, sender=ProjectFormUpload)
def delete_project_form_upload_file(sender, instance, **kwargs):
    """Remove private storage objects only after the database deletion commits."""
    if not instance.file or not instance.file.name:
        return
    storage = instance.file.storage
    name = instance.file.name
    transaction.on_commit(lambda: storage.delete(name))
