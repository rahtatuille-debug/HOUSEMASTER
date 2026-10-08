from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import StudentAccount


@receiver(post_delete, sender=StudentAccount)
def delete_login(sender, instance, **kwargs):
    """No account, no login: the user goes with it (also when the student is deleted)."""
    from django.contrib.auth import get_user_model

    get_user_model().objects.filter(pk=instance.user_id).delete()
