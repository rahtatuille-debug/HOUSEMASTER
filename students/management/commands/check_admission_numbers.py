"""
Counts only: schools where two or more students share an admission number (Student.external_id).

Run before deploying the migration that makes admission numbers unique per school; the migration stops if
any are found. Fix them in the Students page (or the import sheet), then deploy.

  python manage.py check_admission_numbers
"""
from django.core.management.base import BaseCommand

from students.models import Student
from students.preflight import describe, duplicate_admission_numbers


class Command(BaseCommand):
    help = "Report schools whose students share an admission number (read-only, counts and IDs only)."

    def handle(self, *args, **options):
        found = duplicate_admission_numbers(Student)
        if not found:
            self.stdout.write("No shared admission numbers. The uniqueness migration can run.")
            return
        self.stdout.write(f"{len(found)} school(s) with shared admission numbers: {describe(found)}.")
