"""
Anonymise students who left the school long enough ago (F-16).

Off until RETENTION_INACTIVE_STUDENT_YEARS is set (counsel decides the
period), and a dry run unless --apply is given. Uses the same removal as
an admin's "remove personal data" (students/privacy.py), so grades and
attendance stay anonymously and everything identifying goes.

A student counts as left when they are inactive and have a leaving date
(graduated_on, set when their class moves on at the end of the year).
Inactive students without one are reported, not touched.

  python manage.py apply_retention            # what would happen
  python manage.py apply_retention --apply    # do it
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from students.models import Student
from students.privacy import REMOVED_FIRST, REMOVED_LAST, remove_personal_data


class Command(BaseCommand):
    help = "Anonymise students inactive for longer than RETENTION_INACTIVE_STUDENT_YEARS (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Anonymise them (default: only report).")

    def handle(self, *args, apply=False, **options):
        years = getattr(settings, "RETENTION_INACTIVE_STUDENT_YEARS", None)
        if not years:
            self.stdout.write("Retention is off: RETENTION_INACTIVE_STUDENT_YEARS isn't set. Nothing was changed.")
            return
        cutoff = timezone.localdate() - timedelta(days=round(365.25 * years))
        inactive = Student.objects.filter(is_active=False).exclude(first_name=REMOVED_FIRST, last_name=REMOVED_LAST)
        due = inactive.filter(graduated_on__isnull=False, graduated_on__lt=cutoff).select_related("school")
        undated = inactive.filter(graduated_on__isnull=True).count()
        if undated:
            self.stdout.write(f"{undated} inactive student(s) have no leaving date and were skipped.")
        count = due.count()
        if not apply:
            self.stdout.write(f"Would anonymise {count} student(s) who left before {cutoff:%d %B %Y}. "
                              "Run again with --apply to do it.")
            return
        for student in due:
            remove_personal_data(student, actor=None)
        self.stdout.write(f"Anonymised {count} student(s) who left before {cutoff:%d %B %Y}.")
