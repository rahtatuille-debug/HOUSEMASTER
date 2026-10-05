"""Who boarding staff are, where boarders are now, roll calls and parent emails."""
from django.utils import timezone

from accounts.scoping import is_admin
from activity.services import display_name
from students.models import Student

from .models import BoardingHouse, Bed, LeaveRequest, RollCall, RollCallEntry, SickBayVisit


def houses_for(user):
    """The houses this staff member looks after: every house for admins."""
    houses = BoardingHouse.objects.filter(school=user.profile.school)
    return houses if is_admin(user) else houses.filter(staff=user.profile)


def is_boarding_staff(user):
    """House staff and admins, at a school that has turned boarding on."""
    profile = getattr(user, "profile", None)
    return (profile is not None and profile.school.has_boarding
            and (is_admin(user) or profile.boarding_houses.exists()))


def boarders(user, house=None):
    """Active students with a bed in the user's houses (or one of them)."""
    houses = houses_for(user)
    if house is not None:
        houses = houses.filter(pk=house)
    return Student.objects.filter(is_active=True, bed__dorm__house__in=houses) \
        .select_related("bed__dorm__house", "school_class")


def where_now(student_ids):
    """{student: "sick_bay" | "on_leave"} for boarders who aren't simply in the house."""
    out = {sid: "on_leave" for sid in LeaveRequest.objects.filter(
        student_id__in=student_ids, status=LeaveRequest.Status.OUT).values_list("student_id", flat=True)}
    out.update({sid: "sick_bay" for sid in SickBayVisit.objects.filter(
        student_id__in=student_ids, checked_out_at__isnull=True).values_list("student_id", flat=True)})
    return out


def start_roll_call(house, date, session, user):
    """Open a roll call with every boarder in the house; those on leave or in sick bay are filled in."""
    roll_call, created = RollCall.objects.get_or_create(
        house=house, date=date, session=session,
        defaults={"taken_by": user, "taken_by_name": display_name(user)})
    if created:
        students = list(Student.objects.filter(is_active=True, bed__dorm__house=house).values_list("id", flat=True))
        away = where_now(students)
        RollCallEntry.objects.bulk_create([RollCallEntry(roll_call=roll_call, student_id=sid,
                                                         status=away.get(sid, "")) for sid in students])
    return roll_call


def missing_now(user):
    """Boarders marked missing at the latest finished roll call of each of the user's houses."""
    found = []
    for house in houses_for(user):
        latest = house.roll_calls.filter(completed_at__isnull=False).order_by("-date", "-completed_at").first()
        if latest is None:
            continue
        for entry in latest.entries.filter(status=RollCallEntry.Status.MISSING).select_related("student"):
            found.append({"student": entry.student_id,
                          "name": f"{entry.student.first_name} {entry.student.last_name}",
                          "house": house.name, "roll_call": latest.id,
                          "when": f"{latest.get_session_display()} roll call, {latest.date:%a %d %b}",
                          "note": entry.note})
    return found


def overview(user):
    students = list(boarders(user).values_list("id", flat=True))
    away = where_now(students)
    houses = houses_for(user)
    return {
        "houses": houses.count(),
        "boarders": len(students),
        "beds_free": Bed.objects.filter(dorm__house__in=houses, student__isnull=True).count(),
        "on_leave": sum(1 for v in away.values() if v == "on_leave"),
        "sick_bay": sum(1 for v in away.values() if v == "sick_bay"),
        "leave_waiting": LeaveRequest.objects.filter(student_id__in=students,
                                                     status=LeaveRequest.Status.REQUESTED).count(),
        "missing": missing_now(user),
    }


def _parents(student):
    from guardians.models import Guardian

    return Guardian.objects.filter(students=student, email_notifications=True, user__is_active=True) \
        .exclude(user__email="").select_related("user")


def email_parents(student, subject, line):
    """A short email to the student's parents; the details stay in HouseMaster. Returns how many."""
    from guardians.notifications import _footer, send_after_commit

    school = student.school
    messages = [(subject, f"Dear {g.name},\n\n{line}" + _footer(school), g.user.email) for g in _parents(student)]
    if messages:
        send_after_commit(messages)
    return len(messages)


def now():
    return timezone.now()
