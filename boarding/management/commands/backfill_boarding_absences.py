"""
Open an absence for every boarder marked missing at the latest finished roll call of each house.

Before absences existed, the "missing" alert was worked out from the latest roll call. This keeps the boarders
who are flagged today flagged after the upgrade. Dry run unless --apply; safe to repeat (a boarder already
flagged is skipped). Output is counts only.

  python manage.py backfill_boarding_absences            # what would happen
  python manage.py backfill_boarding_absences --apply
"""
from django.core.management.base import BaseCommand

from boarding.models import Absence, BoardingHouse, RollCallEntry
from boarding.services import on_authorised_leave


class Command(BaseCommand):
    help = "Open absences for boarders marked missing at each house's latest finished roll call (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Open them (default: only report).")

    def handle(self, *args, apply=False, **options):
        to_open, skipped = [], 0
        for house in BoardingHouse.objects.all():
            latest = house.roll_calls.filter(completed_at__isnull=False).order_by("-date", "-completed_at").first()
            if latest is None:
                continue
            for entry in latest.entries.filter(status=RollCallEntry.Status.MISSING):
                already = Absence.objects.filter(student_id=entry.student_id, status="open").exists()
                if already or on_authorised_leave(entry.student_id):
                    skipped += 1
                else:
                    to_open.append((entry, house, latest))
        if not apply:
            self.stdout.write(f"Would open {len(to_open)} absence(s); {skipped} skipped (already open, or on authorised "
                              "leave). Run again with --apply to do it.")
            return
        for entry, house, latest in to_open:
            Absence.objects.get_or_create(student_id=entry.student_id, status="open",
                                          defaults={"house": house, "roll_call": latest, "note": entry.note})
        self.stdout.write(f"Opened {len(to_open)} absence(s); {skipped} skipped.")
