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


def _forget_memberships(sender, instance, **kwargs):
    """A membership was added, changed or removed: the user object it was saved with looks it up again."""
    from .memberships import forget

    user = instance._state.fields_cache.get("user")
    if user is not None:
        forget(user)


def connect_membership_signals():
    from django.db.models.signals import post_delete

    from guardians.models import Guardian

    from .models import Profile

    for model in (Profile, Guardian):
        post_save.connect(_forget_memberships, sender=model, dispatch_uid=f"forget_memberships_save_{model.__name__}")
        post_delete.connect(_forget_memberships, sender=model, dispatch_uid=f"forget_memberships_del_{model.__name__}")
