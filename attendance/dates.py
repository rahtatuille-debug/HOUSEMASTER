"""Which dates attendance can be recorded for (F-10)."""
from datetime import timedelta

from gradebook.models import Term
from students.localtime import school_localdate

# Registers can be taken for today and, for schools that prepare the night
# before, tomorrow. Anything later is a typing mistake.
MAX_DAYS_AHEAD = 1
# Older records are only accepted for a period one of the school's terms
# covers (for example importing last year's registers).
MAX_YEARS_BACK = 5


def attendance_date_problem(school, day):
    """A readable reason `day` can't hold attendance at `school`, or None if it's fine."""
    today = school_localdate(school)  # the school's own day (B-4)
    if day > today + timedelta(days=MAX_DAYS_AHEAD):
        return "Attendance can't be recorded for a date in the future."
    earliest = today - timedelta(days=round(365.25 * MAX_YEARS_BACK))
    if day < earliest and not Term.objects.filter(school=school, start_date__lte=day, end_date__gte=day).exists():
        return (f"Attendance more than {MAX_YEARS_BACK} years old can only be recorded for a date one of the "
                "school's terms covers.")
    return None
