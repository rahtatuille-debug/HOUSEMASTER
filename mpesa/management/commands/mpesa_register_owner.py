"""Tell Safaricom where to confirm payments made to the owner's paybill (subscriptions). Run once after setting
the MPESA_* environment variables, and again if the callback address changes."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from mpesa import daraja, services


class Command(BaseCommand):
    help = "Register the owner's paybill confirmation address with M-Pesa (subscriptions)."

    def handle(self, *args, **options):
        if not services.owner_ready():
            raise CommandError("Set MPESA_CALLBACK_BASE_URL, MPESA_SHORTCODE, MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET, "
                               "MPESA_PASSKEY and MPESA_OWNER_CALLBACK_TOKEN first.")
        urls = services.hook_urls(settings.MPESA_OWNER_CALLBACK_TOKEN)
        try:
            daraja.register_c2b(services.owner_credentials(), confirmation_url=urls["confirmation"],
                                validation_url=urls["validation"])
        except daraja.DarajaError as err:
            raise CommandError(str(err))
        self.stdout.write(self.style.SUCCESS(f"Registered paybill {settings.MPESA_SHORTCODE} ({settings.MPESA_ENVIRONMENT})."))
