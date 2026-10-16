"""
PAY-005: the callback token was stored in plain text. Keep a SHA-256 of it to recognise callbacks and an
encrypted copy to build the callback addresses; the addresses Safaricom already has keep working.
"""
from django.db import migrations, models


def protect(apps, schema_editor):
    from mpesa.models import hash_token
    from mpesa.secrets_box import seal

    MpesaAccount = apps.get_model("mpesa", "MpesaAccount")
    for account in MpesaAccount.objects.all():
        account.token_hash = hash_token(account.callback_token)
        # Whatever key the M-Pesa keys themselves use today; `manage.py mpesa_rekey` moves both to a new one.
        account.token_sealed = seal(account.callback_token, require_key=False)
        account.save(update_fields=["token_hash", "token_sealed"])


class Migration(migrations.Migration):
    dependencies = [("mpesa", "0001_initial")]

    operations = [
        migrations.AddField("mpesaaccount", "token_hash",
                            models.CharField(default="", editable=False, max_length=64)),
        migrations.AddField("mpesaaccount", "token_sealed", models.TextField(default="", editable=False)),
        migrations.AddField("mpesaaccount", "token_changed_at", models.DateTimeField(blank=True, null=True)),
        migrations.RunPython(protect, migrations.RunPython.noop),
        migrations.RemoveField("mpesaaccount", "callback_token"),
        migrations.AlterField("mpesaaccount", "token_hash",
                              models.CharField(editable=False, max_length=64, unique=True)),
        migrations.AlterField("mpesaaccount", "token_sealed", models.TextField(editable=False)),
    ]
