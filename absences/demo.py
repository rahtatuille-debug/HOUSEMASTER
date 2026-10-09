"""A few absences reported by a demo school's parents (never real data)."""
import random
from datetime import timedelta

from guardians.models import Guardian
from students.localtime import school_localdate

from .models import AbsenceReport

DETAILS = {"illness": "Fever and a sore throat; we'll see how they are tomorrow.",
           "appointment": "Dentist at 10am, back after lunch.", "family": "Family wedding upcountry.",
           "religious": "", "travel": "", "other": ""}


def fill_demo(school, seed=12, count=8):
    """Returns how many reports were added (today, coming days and last week)."""
    if AbsenceReport.objects.filter(school=school).exists():
        return 0
    rng = random.Random(seed)
    today = school_localdate(school)
    parents = list(Guardian.objects.filter(school=school, students__is_active=True).prefetch_related("students")
                   .order_by("id")[:200])
    added = 0
    for n, g in enumerate(rng.sample(parents, min(count, len(parents)))):
        student = g.students.filter(is_active=True).first()
        start = today + timedelta(days=(0, 0, 0, 1, 2, 3, -3, -5)[n % 8])
        reason = rng.choice(list(DETAILS))
        AbsenceReport.objects.create(
            school=school, student=student, start_date=start, end_date=start + timedelta(days=rng.choice((0, 0, 1))),
            reason=reason, details=DETAILS[reason], reported_by=g.user, reported_by_name=g.name)
        added += 1
    return added
