"""Three size tiers with no price yet (nothing is invoiced until prices are set), and every school
already on HouseMaster marked exempt (the owner's choice: they stay free until changed)."""
from django.db import migrations

TIERS = [("Small", 300), ("Medium", 1000), ("Large", None)]


def forwards(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    Subscription = apps.get_model("billing", "Subscription")
    School = apps.get_model("students", "School")
    if not Plan.objects.exists():
        for name, limit in TIERS:
            Plan.objects.create(name=name, max_students=limit)
    for school in School.objects.filter(subscription__isnull=True):
        Subscription.objects.create(school=school, exempt=True, owner_notes="On HouseMaster before subscriptions began.")


def backwards(apps, schema_editor):
    apps.get_model("billing", "Subscription").objects.filter(
        owner_notes="On HouseMaster before subscriptions began.").delete()
    apps.get_model("billing", "Plan").objects.filter(name__in=[n for n, _ in TIERS], monthly_price__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial"), ("students", "0017_ranking_min_share")]
    operations = [migrations.RunPython(forwards, backwards)]
