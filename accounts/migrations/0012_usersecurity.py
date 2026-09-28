from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill(apps, schema_editor):
    """Every existing user starts at version 0, which old tokens (no claim) also count as."""
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    UserSecurity = apps.get_model("accounts", "UserSecurity")
    existing = set(UserSecurity.objects.values_list("user_id", flat=True))
    UserSecurity.objects.bulk_create(
        [UserSecurity(user_id=pk, token_version=0) for pk in User.objects.values_list("pk", flat=True)
         if pk not in existing],
        batch_size=500,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0011_getting_started"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserSecurity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token_version", models.PositiveIntegerField(default=0)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                                              related_name="security", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
