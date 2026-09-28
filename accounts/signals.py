"""End a user's sessions when their password changes or their account is deactivated."""
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .tokens import bump_token_version

User = get_user_model()


@receiver(pre_save, sender=User)
def note_security_change(sender, instance, update_fields=None, **kwargs):
    instance._end_sessions = False
    if instance.pk is None:
        return
    if update_fields is not None and not {"password", "is_active"} & set(update_fields):
        return
    before = User.objects.filter(pk=instance.pk).values("password", "is_active").first()
    if before is None:
        return
    password_changed = before["password"] != instance.password
    deactivated = before["is_active"] and not instance.is_active
    instance._end_sessions = password_changed or deactivated


@receiver(post_save, sender=User)
def end_sessions(sender, instance, created, **kwargs):
    if getattr(instance, "_end_sessions", False):
        instance._end_sessions = False
        bump_token_version(instance.pk)
