"""What each person sees on the school calendar, and the same as an iCalendar (.ics) feed."""
from datetime import datetime, timedelta

from django.db.models import Q
from django.utils import timezone

from accounts.scoping import can_send_announcements

from .models import Event

MAX_DAYS = 400


def can_manage(user):
    """Leadership, admins and the secretary add and change events."""
    return hasattr(user, "profile") and can_send_announcements(user)


def viewer(user):
    """(school, students) for a parent; (school, None) for staff; (None, None) for anyone else."""
    if getattr(user, "profile", None) is not None:
        return user.profile.school, None
    guardian = getattr(user, "guardian", None)
    if guardian is not None:
        return guardian.school, list(guardian.students.filter(is_active=True).select_related("school_class__year_group"))
    return None, None


def _event_row(e, manage):
    return {
        "id": f"event-{e.id}", "event": e.id, "type": "event", "title": e.title, "kind": e.kind,
        "kind_label": e.get_kind_display(), "start_date": e.start_date, "end_date": e.end_date,
        "start_time": e.start_time, "end_time": e.end_time, "location": e.location, "description": e.description,
        "year_groups": [y.name for y in e.year_groups.all()], "year_group_ids": [y.id for y in e.year_groups.all()],
        "staff_only": e.staff_only, "can_edit": manage,
    }


def items(user, start, end):
    """Everything on this person's calendar from start to end (dates, inclusive), soonest first."""
    from clubs.models import Fixture
    from gradebook.models import Term

    school, students = viewer(user)
    if school is None:
        return []
    staff = students is None
    manage = staff and can_manage(user)
    events = (Event.objects.filter(school=school, start_date__lte=end)
              .filter(Q(end_date__gte=start) | Q(end_date__isnull=True, start_date__gte=start))
              .prefetch_related("year_groups"))
    if not staff:
        years = {s.school_class.year_group_id for s in students if s.school_class_id}
        events = events.filter(staff_only=False).filter(Q(year_groups__isnull=True) | Q(year_groups__in=years)).distinct()
    rows = [_event_row(e, manage) for e in events]

    for term in Term.objects.filter(school=school).filter(
            Q(start_date__range=(start, end)) | Q(end_date__range=(start, end))):
        for when, word in ((term.start_date, "starts"), (term.end_date, "ends")):
            if when and start <= when <= end:
                rows.append({"id": f"term-{term.id}-{word}", "type": "term", "title": f"{term.name} {word}",
                             "kind": "term", "kind_label": "Term dates", "start_date": when, "end_date": None,
                             "start_time": None, "end_time": None, "location": "", "description": "",
                             "year_groups": [], "staff_only": False, "can_edit": False})

    fixtures = Fixture.objects.filter(club__school=school, club__is_active=True, date__range=(start, end)).select_related("club")
    if not staff:
        ids = [s.id for s in students]
        fixtures = fixtures.filter(club__members__student__in=ids).distinct().prefetch_related("players")
    for f in fixtures:
        picked = [] if staff else [s.first_name for s in students if any(p.id == s.id for p in f.players.all())]
        rows.append({
            "id": f"fixture-{f.id}", "type": "fixture", "fixture": f.id, "club": f.club_id,
            "title": f"{f.club.name}{f' ({f.team})' if f.team else ''} v {f.opponent}", "kind": "fixture",
            "kind_label": "Fixture", "start_date": f.date, "end_date": None, "start_time": f.start_time, "end_time": None,
            "location": ", ".join(x for x in (f.get_venue_display(), f.location) if x), "description": f.competition,
            "year_groups": [], "staff_only": False, "can_edit": False, "picked": picked,
        })
    rows.sort(key=lambda r: (r["start_date"], r["start_time"] or datetime.min.time(), r["title"]))
    return rows


# iCalendar ---------------------------------------------------------------

def _text(value):
    return (str(value).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n")
            .replace("\n", "\\n"))


def _fold(line):
    """Lines longer than 75 octets continue on the next line, which starts with a space (RFC 5545)."""
    data = line.encode()
    if len(data) <= 75:
        return line
    parts, current = [], b""
    for ch in line:
        b = ch.encode()
        if len(current) + len(b) > (75 if not parts else 74):
            parts.append(current.decode())
            current = b""
        current += b
    parts.append(current.decode())
    return "\r\n ".join(parts)


def ical(user, school, host):
    """This person's calendar from two months ago to a year ahead, as an .ics file."""
    from students.localtime import school_localdate

    today = school_localdate(school)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//HouseMaster//School calendar//EN", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{_text(school.name)}"]
    stamp = timezone.now().strftime("%Y%m%dT%H%M%SZ")
    for r in items(user, today - timedelta(days=60), today + timedelta(days=365)):
        lines += ["BEGIN:VEVENT", f"UID:{r['id']}@{host}", f"DTSTAMP:{stamp}", f"SUMMARY:{_text(r['title'])}"]
        first, last = r["start_date"], r["end_date"] or r["start_date"]
        if r["start_time"]:
            lines.append(f"DTSTART:{first:%Y%m%d}T{r['start_time']:%H%M%S}")
            end_time = r["end_time"] or (datetime.combine(first, r["start_time"]) + timedelta(hours=1)).time()
            lines.append(f"DTEND:{last:%Y%m%d}T{end_time:%H%M%S}")
        else:
            lines += [f"DTSTART;VALUE=DATE:{first:%Y%m%d}", f"DTEND;VALUE=DATE:{last + timedelta(days=1):%Y%m%d}"]
        if r["location"]:
            lines.append(f"LOCATION:{_text(r['location'])}")
        if r["description"]:
            lines.append(f"DESCRIPTION:{_text(r['description'])}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
