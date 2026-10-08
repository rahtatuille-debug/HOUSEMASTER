"""A term's worth of calendar events for a demo school (never real data)."""
from datetime import time, timedelta

from students.localtime import school_localdate
from students.models import YearGroup

from .models import Event


def fill_demo(school):
    """Returns how many events were added."""
    if Event.objects.filter(school=school).exists():
        return 0
    today = school_localdate(school)
    monday = today - timedelta(days=today.weekday())
    years = list(YearGroup.objects.filter(school=school).order_by("order", "name"))
    rows = [
        ("Sports day", "sport", 9, None, time(9), time(15), "Main field", None, False),
        ("Parents' evening", "meeting", 3, None, time(16), time(19), "School hall", None, False),
        ("Half-term holiday", "holiday", 18, 22, None, None, "", None, False),
        ("Staff training day", "staff", 25, None, None, None, "", None, True),
        ("Science museum trip", "trip", 11, None, time(8, 30), time(16), "City science museum", years[:1], False),
        ("Mock exams", "exam", 30, 34, None, None, "Exam hall", years[-1:], False),
        ("Winter concert", "performance", 39, None, time(18), time(20), "School hall", None, False),
    ]
    for title, kind, start, end, t1, t2, where, groups, staff_only in rows:
        event = Event.objects.create(
            school=school, title=title, kind=kind, start_date=monday + timedelta(days=start),
            end_date=monday + timedelta(days=end) if end else None, start_time=t1, end_time=t2, location=where,
            staff_only=staff_only, created_by_name="Demo", description="")
        if groups:
            event.year_groups.set(groups)
    return len(rows)
