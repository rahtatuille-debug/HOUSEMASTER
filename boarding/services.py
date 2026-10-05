"""Who boarding staff are, where boarders are now, roll calls and parent emails."""
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from accounts.scoping import is_admin
from activity.services import display_name, log_activity, student_name
from students.models import Student

from .models import Absence, Bed, BoardingHouse, LeaveRequest, RollCall, RollCallEntry, SickBayVisit


def houses_for(user, archived=False):
    """The houses this staff member looks after: every house for admins. Archived houses only when asked for
    (their history stays readable, but nobody is boarded there or takes new roll calls)."""
    houses = BoardingHouse.objects.filter(school=user.profile.school)
    if archived is not None:  # None: both, for reading history
        houses = houses.filter(is_archived=archived)
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


def on_authorised_leave(student_id, at=None):
    """Signed out on leave, or approved leave whose dates cover this moment (a boarder who is allowed to be away)."""
    at = at or timezone.now()
    return LeaveRequest.objects.filter(student_id=student_id).filter(
        Q(status=LeaveRequest.Status.OUT) |
        Q(status=LeaveRequest.Status.APPROVED, leaving_at__lte=at, returning_at__gte=at)).exists()


def open_absence(student, house, roll_call, actor, note=""):
    """Flag a boarder as missing until someone resolves it. Returns the absence, or None when there's nothing to
    flag (they are on authorised leave) or one is already open."""
    if on_authorised_leave(student.id):
        return None
    try:
        with transaction.atomic():
            absence = Absence.objects.create(student=student, house=house, roll_call=roll_call, note=note[:300])
    except IntegrityError:  # already open: one open absence per boarder
        return None
    log_activity(school=house.school, actor=actor, action="boarding.absence_opened", target=student,
                 summary=f"{student_name(student)} was marked missing from {house.name}", house=house.id,
                 roll_call=roll_call.id if roll_call else None)
    return absence


def open_absences_from(roll_call, actor):
    """When a roll call is finished: every boarder marked missing (and not on authorised leave) is flagged."""
    opened = 0
    for entry in roll_call.entries.filter(status=RollCallEntry.Status.MISSING).select_related("student__school"):
        if open_absence(entry.student, roll_call.house, roll_call, actor, entry.note):
            opened += 1
    return opened


def resolve_absence(absence, resolution, actor, note=""):
    absence.status = Absence.Status.RESOLVED
    absence.resolution = resolution
    absence.resolved_at = timezone.now()
    absence.resolved_by = actor if actor is not None and getattr(actor, "is_authenticated", False) else None
    absence.resolved_by_name = display_name(actor) if absence.resolved_by else "System"
    absence.resolution_note = note[:500]
    absence.save()
    log_activity(school=absence.house.school, actor=absence.resolved_by, action="boarding.absence_resolved",
                 target=absence.student, summary=f"{student_name(absence.student)}'s absence from "
                                                 f"{absence.house.name}: {absence.get_resolution_display().lower()}",
                 house=absence.house_id, resolution=resolution)
    return absence


def missing_now(user):
    """Every open absence in the user's houses, oldest first. They stay until a person resolves them."""
    absences = Absence.objects.filter(status=Absence.Status.OPEN, house__in=houses_for(user)) \
        .select_related("student", "house", "roll_call").order_by("opened_at", "id")
    return [absence_row(a) for a in absences]


def absence_row(a):
    when = (f"{a.roll_call.get_session_display()} roll call, {a.roll_call.date:%a %d %b}" if a.roll_call
            else f"{a.opened_at:%a %d %b}")
    return {"id": a.id, "student": a.student_id, "name": f"{a.student.first_name} {a.student.last_name}",
            "house": a.house.name, "roll_call": a.roll_call_id, "when": when, "note": a.note,
            "since": a.opened_at}


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


def delete_school_history(school):
    """Only for deleting a whole school (the demo resets): roll calls and absences protect their house from a
    one-off delete, so they go first. Never used to remove a single house."""
    Absence.objects.filter(house__school=school).delete()
    RollCall.objects.filter(house__school=school).delete()
