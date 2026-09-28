"""
One account per email address, whatever its case (F-13). Accounts without
an email (none are created by the app, but the admin allows it) are left
alone.
"""
from django.db import migrations
from django.db.models import Count
from django.db.models.functions import Lower

MAX_IDS_SHOWN = 50


def refuse_duplicate_emails(apps, schema_editor):
    """
    Stop before adding the index if accounts already share an email, so the
    deploy fails cleanly. Only user IDs are printed, never the addresses.
    See docs/HUMAN_ACTIONS.md (H-6).
    """
    User = apps.get_model("auth", "User")
    shared = list(
        User.objects.exclude(email="").annotate(lower_email=Lower("email")).values("lower_email")
        .annotate(n=Count("id")).filter(n__gt=1).values_list("lower_email", flat=True)
    )
    if not shared:
        return
    ids = list(
        User.objects.annotate(lower_email=Lower("email")).filter(lower_email__in=shared)
        .order_by("pk").values_list("pk", flat=True)
    )
    shown = ", ".join(str(pk) for pk in ids[:MAX_IDS_SHOWN])
    more = f" and {len(ids) - MAX_IDS_SHOWN} more" if len(ids) > MAX_IDS_SHOWN else ""
    raise RuntimeError(
        f"{len(shared)} email address(es) are shared by more than one account (user IDs {shown}{more}). "
        "Give each account its own address or remove the extra ones, then deploy again. "
        "'manage.py check_duplicate_emails' and scripts/preflight_duplicate_emails.sql list them."
    )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0012_usersecurity"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(refuse_duplicate_emails, migrations.RunPython.noop),
        # Valid on both SQLite and PostgreSQL: a partial index on LOWER(email).
        migrations.RunSQL(
            "CREATE UNIQUE INDEX IF NOT EXISTS accounts_user_email_ci_unique "
            "ON auth_user (LOWER(email)) WHERE email <> ''",
            reverse_sql="DROP INDEX IF EXISTS accounts_user_email_ci_unique",
        ),
    ]
