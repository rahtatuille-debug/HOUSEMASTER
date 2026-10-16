"""Ask M-Pesa about payment prompts whose answer never came (run every 10 minutes: docs/HUMAN_ACTIONS.md)."""
from django.core.management.base import BaseCommand

from mpesa.services import sweep


class Command(BaseCommand):
    help = "Settle M-Pesa payment prompts whose callback never arrived."

    def handle(self, *args, **options):
        counts = sweep(limit=200)
        self.stdout.write(f"Asked M-Pesa about {counts['asked']} prompt(s): {counts['paid']} paid, "
                          f"{counts['failed']} not paid.")
