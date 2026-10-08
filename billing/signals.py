from django.db.models.signals import post_save
from django.dispatch import receiver

from students.models import School


@receiver(post_save, sender=School)
def start_subscription(sender, instance, created, **kwargs):
    """Every new school has a subscription (not exempt: there is no free trial)."""
    if created:
        from .models import Subscription

        Subscription.objects.get_or_create(school=instance)
