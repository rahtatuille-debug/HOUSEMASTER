"""
Record the class on finalized reports from before classes were recorded, but only where it is certain.

Today's class is only the class of the time if nothing could have moved the student since the term began: no
year-end move-up in the school and no edit to the student since the term started, with the activity log going back
that far. Everything else is left as "not recorded" (an admin can set it with correct-class). Dry run unless
--apply; output is counts only.

  python manage.py backfill_report_classes            # what would happen
  python manage.py backfill_report_classes --apply
"""
from datetime import datetime, time

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from activity.models import ActivityLog
from reporting.models import StudentReport

MOVES = ["student.updated", "student.deactivated", "student.reactivated", "student.promoted"]


def is_certain(report):
    since = timezone.make_aware(datetime.combine(report.term.start_date, time.min))
    logs = ActivityLog.objects.filter(school_id=report.student.school_id)
    first = logs.order_by("created_at").values_list("created_at", flat=True).first()
    if first is None or first > since:
        return False  # the log doesn't go back far enough to tell
    moved = logs.filter(created_at__gte=since).filter(action="school.year_end").exists() or logs.filter(
        created_at__gte=since, action__in=MOVES, target_type="student", target_id=report.student_id).exists()
    return not moved


class Command(BaseCommand):
    help = "Record the class on old finalized reports where it is certain (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Record them (default: only report).")

    def handle(self, *args, apply=False, **options):
        reports = StudentReport.objects.filter(status="finalized", class_name="", class_recorded_at__isnull=True) \
            .select_related("term", "student__school", "student__school_class__year_group__school")
        certain, unsure = [], 0
        for report in reports:
            if is_certain(report):
                certain.append(report)
            else:
                unsure += 1
        if not apply:
            self.stdout.write(f"Would record {len(certain)} report class(es); {unsure} left as 'not recorded'. "
                              "Run again with --apply to do it.")
            return
        with transaction.atomic():
            for report in certain:
                report.record_class()
            StudentReport.objects.bulk_update(certain, StudentReport.CLASS_FIELDS, batch_size=1000)
        self.stdout.write(f"Recorded {len(certain)} report class(es); {unsure} left as 'not recorded'.")
