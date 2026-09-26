"""
Import a school's Excel workbook (Students / Grades / Attendance sheets).

Admins can do the same from the app (Setup → Import from Excel), with a
preview first. Both use students.importer, which documents the columns.

Usage:
  python manage.py import_school_workbook path/to/workbook.xlsx --school "Sample School" [--preview]
"""
from django.core.management.base import BaseCommand, CommandError

from students.importer import WorkbookError, import_workbook
from students.models import School


class Command(BaseCommand):
    help = "Import a school's Students/Grades/Attendance Excel workbook into HouseMaster."

    def add_arguments(self, parser):
        parser.add_argument("workbook_path", type=str)
        parser.add_argument("--school", type=str, required=True, help="School name (created if it doesn't exist)")
        parser.add_argument("--preview", action="store_true", help="Show what would happen without saving")

    def handle(self, *args, **options):
        school, _ = School.objects.get_or_create(name=options["school"])
        try:
            with open(options["workbook_path"], "rb") as f:
                result = import_workbook(f, school, commit=not options["preview"])
        except FileNotFoundError:
            raise CommandError(f"Workbook not found: {options['workbook_path']}")
        except WorkbookError as exc:
            raise CommandError(str(exc))

        c = result["counts"]
        verb = "Would import" if options["preview"] else "Imported"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} for '{school.name}': {c['students_created']} new students, {c['students_updated']} updated, "
            f"{c['grades']} grades, {c['attendance']} attendance records."
        ))
        for kind, names in result["created"].items():
            if names:
                self.stdout.write(f"New {kind.replace('_', ' ')}: {', '.join(names)}")
        for e in result["errors"]:
            self.stdout.write(self.style.WARNING(f"{e['sheet']} row {e['row']}: {e['message']}"))
