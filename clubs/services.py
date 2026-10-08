"""Who may run a club, and what parents see of their child's clubs."""
from django.db.models import Count, Q

from accounts.scoping import is_leader
from students.localtime import school_localdate

from .models import ClubAttendance, Fixture


def can_manage(user, club):
    """Leadership, admins and the club's own staff run a club."""
    return is_leader(user) or any(leader.pk == user.pk for leader in club.leaders.all())


def leader_names(club):
    return [getattr(getattr(u, "profile", None), "name", "") or u.get_full_name() or "Staff" for u in club.leaders.all()]


def attendance_counts(club, student_ids):
    """{student_id: {"present", "absent", "excused", "sessions"}} for this club's registers."""
    rows = (ClubAttendance.objects.filter(session__club=club, student_id__in=student_ids)
            .values("student_id").annotate(
                present=Count("id", filter=Q(status="present")), absent=Count("id", filter=Q(status="absent")),
                excused=Count("id", filter=Q(status="excused")), sessions=Count("id")))
    return {r.pop("student_id"): r for r in rows}


def fixture_row(fixture, selected=None, with_report=True):
    row = {
        "id": fixture.id, "club": fixture.club_id, "club_name": fixture.club.name, "date": fixture.date,
        "start_time": fixture.start_time, "opponent": fixture.opponent, "venue": fixture.venue,
        "venue_label": fixture.get_venue_display(), "location": fixture.location, "competition": fixture.competition,
        "team": fixture.team, "our_score": fixture.our_score, "their_score": fixture.their_score,
        "result_note": fixture.result_note, "outcome": fixture.outcome,
    }
    if selected is not None:
        row["selected"] = selected
    if with_report:
        row["report"] = fixture.report
    return row


def parent_view(student):
    """A child's active clubs: when they meet, who runs them, attendance and fixtures."""
    today = school_localdate(student.school)
    memberships = (student.club_memberships.filter(club__is_active=True)
                   .select_related("club").prefetch_related("club__leaders__profile").order_by("club__name"))
    picked = set(student.fixtures.values_list("id", flat=True))
    clubs = []
    for m in memberships:
        club = m.club
        counts = attendance_counts(club, [student.id]).get(student.id, {"present": 0, "absent": 0, "excused": 0, "sessions": 0})
        fixtures = Fixture.objects.filter(club=club).select_related("club")
        played = Q(our_score__isnull=False) | ~Q(result_note="")
        upcoming = list(fixtures.filter(date__gte=today).exclude(played).order_by("date", "start_time")[:5])
        results = list(fixtures.filter(played).order_by("-date", "-id")[:5])
        clubs.append({
            "id": club.id, "name": club.name, "kind_label": club.get_kind_display(), "meets": club.meets,
            "location": club.location, "leaders": leader_names(club), "role": m.role, "joined_on": m.joined_on,
            "attendance": counts,
            # The match report is for the families of the squad.
            "upcoming": [fixture_row(f, f.id in picked, with_report=False) for f in upcoming],
            "results": [fixture_row(f, f.id in picked, with_report=f.id in picked) for f in results],
        })
    return clubs


def notify_squad(fixture, student_ids):
    """
    Email the parents of students just picked for a fixture (one email per
    parent). Only when, where and who against; never the rest of the squad.
    Returns how many parents are emailed.
    """
    from guardians.models import Guardian
    from guardians.notifications import _footer, send_after_commit

    if not student_ids:
        return 0
    club, school = fixture.club, fixture.club.school
    when = f"{fixture.date.strftime('%A')} {fixture.date.day} {fixture.date.strftime('%B')}"
    if fixture.start_time:
        when += f" at {fixture.start_time.strftime('%H:%M')}"
    where = fixture.get_venue_display() + (f", {fixture.location}" if fixture.location else "")
    parents = (Guardian.objects.filter(students__in=student_ids, email_notifications=True, user__is_active=True)
               .exclude(user__email="").select_related("user").prefetch_related("students").distinct())
    messages = []
    for g in parents:
        kids = sorted(s.first_name for s in g.students.all() if s.id in student_ids)
        names = " and ".join(kids)
        messages.append((
            f"{names} {'is' if len(kids) == 1 else 'are'} in the {club.name} squad v {fixture.opponent}",
            f"Dear {g.name},\n\n{names} {'has' if len(kids) == 1 else 'have'} been picked for {club.name}"
            f"{f' ({fixture.team})' if fixture.team else ''} v {fixture.opponent}.\n\n"
            f"When: {when}\nWhere: {where}" + _footer(school),
            g.user.email,
        ))
    if messages:
        send_after_commit(messages)
    return len(messages)


def my_clubs(user):
    """The clubs this person runs, with their fixtures in the next two weeks (for the teacher's Home page)."""
    from datetime import timedelta

    from .models import Club

    school = user.profile.school
    today = school_localdate(school)
    clubs = (Club.objects.filter(school=school, leaders=user, is_active=True)
             .annotate(member_count=Count("members", filter=Q(members__student__is_active=True), distinct=True)))
    return [{
        "id": c.id, "name": c.name, "meets": c.meets, "member_count": c.member_count,
        "fixtures": [fixture_row(f, with_report=False) for f in Fixture.objects.filter(
            club=c, date__gte=today, date__lte=today + timedelta(days=14)).select_related("club")
            .order_by("date", "start_time")[:5]],
    } for c in clubs]
