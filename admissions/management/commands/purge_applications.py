"""
Delete admissions applications the school no longer needs:

- applications never confirmed whose confirmation link has expired;
- closed applications (declined, withdrawn, enrolled) older than the school's retention period, for schools that
  set one (Admissions settings, retention_days). Off by default: without it, nothing closed is deleted.

Open applications are never deleted. Dry run unless --apply; output is counts only.

  python manage.py purge_applications            # what would happen
  python manage.py purge_applications --apply
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from admissions.models import AdmissionsSettings, Application

CLOSED = [Application.Status.DECLINED, Application.Status.WITHDRAWN, Application.Status.ENROLLED]


class Command(BaseCommand):
    help = "Delete expired unconfirmed applications, and closed ones past a school's retention period (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Delete them (default: only report).")

    def handle(self, *args, apply=False, **options):
        now = timezone.now()
        expired = Application.objects.filter(confirmed_at__isnull=True, confirm_expires_at__lt=now)
        old = Q(pk__in=[])
        for found in AdmissionsSettings.objects.filter(retention_days__isnull=False):
            old |= Q(school_id=found.school_id, updated_at__lt=now - timedelta(days=found.retention_days))
        closed = Application.objects.filter(old, status__in=CLOSED, confirmed_at__isnull=False)
        counts = (expired.count(), closed.count())
        what = f"{counts[0]} unconfirmed application(s) whose link expired and {counts[1]} closed application(s) " \
               "past their school's retention period"
        if not apply:
            self.stdout.write(f"Would delete {what}. Run again with --apply to do it.")
            return
        expired.delete()
        closed.delete()
        self.stdout.write(f"Deleted {what}.")
