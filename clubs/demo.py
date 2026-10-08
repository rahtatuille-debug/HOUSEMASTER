"""Clubs, teams, registers and fixtures for a demo school (never real data)."""
import random
from datetime import timedelta

from accounts.models import Profile
from students.localtime import school_localdate
from students.models import Student

from .models import Club, ClubAttendance, ClubMember, ClubSession, Fixture

CLUBS = [
    ("Football", "sport", "Tuesdays and Thursdays 3:30pm", "Main field", True),
    ("Netball", "sport", "Wednesdays 3:30pm", "Courts", True),
    ("Athletics", "sport", "Mondays 3:30pm", "Track", True),
    ("Debating society", "academic", "Fridays at lunch", "Library", True),
    ("Choir", "music", "Mondays at lunch", "Music room", False),
    ("Drama club", "arts", "Thursdays 3:30pm", "Hall", False),
    ("Environment club", "service", "Wednesdays at lunch", "Science lab 2", False),
]
OPPONENTS = ["St Mary's School", "Hillcrest Academy", "Riverside High", "Kings College", "Lakeside School",
             "Greenfield School", "Westbrook Academy"]


def fill_demo(school, seed=7):
    """Returns how many clubs were added."""
    rng = random.Random(seed)
    today = school_localdate(school)
    staff = list(Profile.objects.filter(school=school, role=Profile.Role.TEACHER, user__is_active=True)
                 .select_related("user").order_by("id"))
    students = list(Student.objects.filter(school=school, is_active=True).order_by("id"))
    if not staff or len(students) < 20:
        return 0
    added = 0
    for name, kind, meets, location, has_fixtures in CLUBS:
        if Club.objects.filter(school=school, name=name).exists():
            continue
        club = Club.objects.create(school=school, name=name, kind=kind, meets=meets, location=location,
                                   description=f"{name} for every year group. All welcome.")
        club.leaders.set([p.user for p in rng.sample(staff, min(len(staff), rng.choice((1, 2))))])
        members = rng.sample(students, min(len(students), rng.randint(12, 24)))
        ClubMember.objects.bulk_create([
            ClubMember(club=club, student=s, joined_on=today - timedelta(days=rng.randint(20, 300)),
                       role="Captain" if i == 0 and has_fixtures else "") for i, s in enumerate(members)])
        for weeks in range(1, 7):  # six weekly registers
            session = ClubSession.objects.create(club=club, date=today - timedelta(weeks=weeks), taken_by_name="Demo")
            ClubAttendance.objects.bulk_create([
                ClubAttendance(session=session, student=s,
                               status=rng.choices(("present", "absent", "excused"), (85, 10, 5))[0]) for s in members])
        if has_fixtures:
            for days in (-24, -17, -10, -3, 4, 11):
                ours, theirs = (rng.randint(0, 4), rng.randint(0, 3)) if days < 0 else (None, None)
                fixture = Fixture.objects.create(
                    club=club, date=today + timedelta(days=days), opponent=rng.choice(OPPONENTS),
                    venue=rng.choice(("home", "away")), competition="Schools league", team="First team",
                    our_score=ours, their_score=theirs,
                    report="A strong team performance." if days < 0 else "")
                fixture.players.set([m.id for m in members[:11]])
        added += 1
    return added
