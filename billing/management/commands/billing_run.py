from django.core.management.base import BaseCommand

from billing import services
from billing.models import Subscription


class Command(BaseCommand):
    help = "Issue the coming month's invoices and send payment reminders. Run once a day."

    def handle(self, *args, **options):
        issued = 0
        for sub in Subscription.objects.filter(exempt=False).select_related("school"):
            if services.issue_due(sub.school):
                issued += 1
            services.refresh(sub.school)
        reminded = services.send_reminders()
        self.stdout.write(f"Issued {issued} invoice(s); sent {reminded} reminder(s).")
