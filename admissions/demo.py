"""Admissions for demo schools: the form open, and applications at every stage."""
import random
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from students.models import YearGroup
from students.samples import names

from .models import Application
from .services import settings_for

STAGES = ["new"] * 4 + ["reviewing"] * 3 + ["interview"] * 2 + ["offered"] * 2 + ["accepted", "waitlist", "declined",
                                                                                     "withdrawn"]


def fill_demo(school, domain):
    """Open the form and add applications. `domain` is the school's demo email domain. Returns how many."""
    rng = random.Random(f"admissions-{school.id}")
    found = settings_for(school)
    found.is_open = True
    found.intro = (f"Thank you for your interest in {school.name}. Fill in this form and our admissions team will "
                   "contact you within a week.")
    found.save()
    years = list(YearGroup.objects.filter(school=school).order_by("order"))
    if not years:
        return 0
    girls, boys, surnames = names(school.country)
    now = timezone.now()
    rows = []
    for n, status in enumerate(STAGES, start=1):
        female = rng.random() < 0.5
        last = rng.choice(surnames)
        year = years[0] if rng.random() < 0.6 else rng.choice(years)
        rows.append(Application(
            school=school, status=status, year_group=year, start="Next term",
            first_name=rng.choice(girls if female else boys), last_name=last,
            date_of_birth=date(date.today().year - 11 - years.index(year), 1, 1) + timedelta(days=rng.randint(0, 360)),
            gender="female" if female else "male", current_school=rng.choice(
                ["Riverside Primary", "St Mary's School", "Hillcrest Academy", "Greenfields School"]),
            mode_of_learning="boarding" if school.has_boarding and rng.random() < 0.5 else "day",
            parent_name=f"{rng.choice(girls)} {last}", parent_email=f"applicant{n}@{domain}",
            parent_phone=f"+254 7{rng.randint(10, 99)} {rng.randint(100, 999)} {rng.randint(100, 999)}",
            relationship="mother", notes="Keen on music and football." if rng.random() < 0.3 else "",
            interview_at=timezone.make_aware(datetime.combine(date.today() + timedelta(days=rng.randint(2, 9)),
                                                              time(10))) if status == "interview" else None,
            decided_by_name="Admissions office" if status not in ("new", "reviewing") else "",
            confirmed_at=now,  # the family confirmed their email
        ))
    Application.objects.bulk_create(rows)
    # Spread the dates over the last few weeks.
    for n, app in enumerate(Application.objects.filter(school=school).order_by("id")):
        when = now - timedelta(days=(len(STAGES) - n) * 2)
        Application.objects.filter(pk=app.pk).update(created_at=when, confirmed_at=when)
    return len(rows)
