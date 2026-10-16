"""
Re-encrypt every school's M-Pesa keys and callback secret with the first MPESA_ENCRYPTION_KEY.

Run once after setting MPESA_ENCRYPTION_KEY for the first time (secrets were encrypted with a key derived from
SECRET_KEY until then), and after putting a new key first in the list. Once it reports nothing left on an old key,
the old key can be dropped from the list.
"""
from django.core.management.base import BaseCommand, CommandError

from mpesa.models import MpesaAccount
from mpesa.secrets_box import UnreadableSecret, configured_keys, reseal, unseal

FIELDS = ("consumer_key", "consumer_secret", "passkey", "token_sealed")


class Command(BaseCommand):
    help = "Re-encrypt the schools' M-Pesa secrets with the first MPESA_ENCRYPTION_KEY."

    def handle(self, *args, **options):
        if not configured_keys():
            raise CommandError("Set MPESA_ENCRYPTION_KEY first (docs/ENVIRONMENT.md).")
        done, unreadable = 0, []
        for account in MpesaAccount.objects.select_related("school"):
            try:
                for field in FIELDS:
                    unseal(getattr(account, field))  # every field readable before anything is rewritten
            except UnreadableSecret:
                unreadable.append(account.school.name)
                continue
            for field in FIELDS:
                setattr(account, field, reseal(getattr(account, field)))
            account.save(update_fields=list(FIELDS))
            done += 1
        self.stdout.write(f"Re-encrypted the M-Pesa secrets of {done} school(s) with the first key.")
        if unreadable:
            self.stdout.write(self.style.WARNING(
                f"Couldn't read the secrets of: {', '.join(unreadable)}. Their admins need to enter the Daraja keys "
                "again and press \"New callback address\"."))
