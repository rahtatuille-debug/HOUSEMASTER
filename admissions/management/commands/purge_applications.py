"""
Delete admissions applications that were never confirmed and whose confirmation link has expired.

Dry run unless --apply; output is counts only.

  python manage.py purge_applications            # what would happen
  python manage.py purge_applications --apply
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from admissions.models import Application


class Command(BaseCommand):
    help = "Delete expired unconfirmed admissions applications (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Delete them (default: only report).")

    def handle(self, *args, apply=False, **options):
        expired = Application.objects.filter(confirmed_at__isnull=True, confirm_expires_at__lt=timezone.now())
        count = expired.count()
        if not apply:
            self.stdout.write(f"Would delete {count} unconfirmed application(s) whose link expired. "
                              "Run again with --apply to do it.")
            return
        expired.delete()
        self.stdout.write(f"Deleted {count} unconfirmed application(s) whose link expired.")
