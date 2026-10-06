"""
Free beds held by people who have left, or who no longer board.

Before this fix, leaving, graduating and going back to day didn't give up the bed. Dry run unless --apply;
counts only. It uses the same function as every other path (boarding.services.release_boarders).

  python manage.py release_stale_beds            # what would happen
  python manage.py release_stale_beds --apply
"""
from django.core.management.base import BaseCommand
from django.db.models import Q

from boarding.models import Bed
from boarding.services import release_boarders


class Command(BaseCommand):
    help = "Free beds held by inactive or non-boarding students (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Free them (default: only report).")

    def handle(self, *args, apply=False, **options):
        stale = Bed.objects.filter(Q(student__is_active=False) | (Q(student__isnull=False) &
                                                                  ~Q(student__mode_of_learning="boarding")))
        ids = list(stale.values_list("student_id", flat=True))
        if not apply:
            self.stdout.write(f"Would free {len(ids)} bed(s). Run again with --apply to do it.")
            return
        released = release_boarders(ids, "left_school", None)
        self.stdout.write(f"Freed {released} bed(s).")
