"""
Staff cover: who is away on a date, which of their lessons need cover, and
who is free to take them. A lesson needs cover when its teacher is away
(the whole day, or that period), or when it has no active teacher.
"""
from collections import defaultdict

from django.db.models import Q

from accounts.models import Profile
from activity.services import display_name, log_activity

from .models import DAY_NAMES, CoverAssignment, Lesson, StaffAbsence
from .services import lesson_row, school_days


def absent_on(school, day):
    """{profile id: None (all day) or a set of period ids} for everyone away on `day`."""
    away = {}
    for absence in StaffAbsence.objects.filter(school=school, start_date__lte=day, end_date__gte=day) \
            .prefetch_related("periods"):
        periods = {p.id for p in absence.periods.all()}
        if not periods or away.get(absence.teacher_id, set()) is None:
            away[absence.teacher_id] = None
        else:
            away[absence.teacher_id] = away.get(absence.teacher_id, set()) | periods
    return away


def _is_away(away, teacher_id, period_id):
    return teacher_id in away and (away[teacher_id] is None or period_id in away[teacher_id])


def needs_cover(lesson, day, away=None):
    away = absent_on(lesson.school, day) if away is None else away
    teacher = lesson.teacher
    return teacher is None or not teacher.user.is_active or _is_away(away, lesson.teacher_id, lesson.period_id)


def free_staff(school, day, period_id, away=None, busy=None):
    """Active teaching staff with no lesson in that period, not away and not already covering it."""
    away = absent_on(school, day) if away is None else away
    if busy is None:
        busy = _busy(school, day)
    staff = Profile.objects.filter(school=school, user__is_active=True).exclude(role=Profile.Role.GOVERNOR) \
        .select_related("user")
    lessons_today = _lessons_today(school, day)
    rows = [{"id": p.id, "name": p.name, "lessons_today": lessons_today.get(p.id, 0)}
            for p in staff if (p.id, period_id) not in busy and not _is_away(away, p.id, period_id)]
    # Those with the lightest day first.
    return sorted(rows, key=lambda r: (r["lessons_today"], r["name"]))


def _lessons_today(school, day):
    counts = defaultdict(int)
    for teacher_id in Lesson.objects.filter(school=school, day=day.isoweekday(), teacher__isnull=False) \
            .values_list("teacher_id", flat=True):
        counts[teacher_id] += 1
    for teacher_id in CoverAssignment.objects.filter(school=school, date=day, cover_teacher__isnull=False) \
            .values_list("cover_teacher_id", flat=True):
        counts[teacher_id] += 1
    return counts


def _busy(school, day):
    """(teacher, period) pairs already taken that day: their own lessons and cover they're doing."""
    busy = set(Lesson.objects.filter(school=school, day=day.isoweekday(), teacher__isnull=False)
               .values_list("teacher_id", "period_id"))
    busy |= set(CoverAssignment.objects.filter(school=school, date=day, cover_teacher__isnull=False)
                .values_list("cover_teacher_id", "lesson__period_id"))
    return busy


def cover_day(school, day):
    """Every lesson needing cover on `day`, with who's away, the cover arranged and who is free."""
    if day.isoweekday() not in school_days(school):
        return {"date": day, "day_name": DAY_NAMES[day.isoweekday()], "school_day": False, "absent": [], "lessons": []}
    away = absent_on(school, day)
    busy = _busy(school, day)
    reasons = {}
    for absence in StaffAbsence.objects.filter(school=school, start_date__lte=day, end_date__gte=day) \
            .select_related("teacher__user"):
        reasons.setdefault(absence.teacher_id, absence)
    lessons = Lesson.objects.filter(school=school, day=day.isoweekday()).filter(
        Q(teacher__isnull=True) | Q(teacher__user__is_active=False) | Q(teacher_id__in=list(away))) \
        .select_related("school_class", "subject", "teacher__user", "room", "period")
    arranged = {c.lesson_id: c for c in CoverAssignment.objects.filter(school=school, date=day)
                .select_related("cover_teacher")}
    rows = []
    for lesson in lessons:
        if not needs_cover(lesson, day, away):
            continue
        absence = reasons.get(lesson.teacher_id)
        cover = arranged.get(lesson.id)
        why = (absence.get_reason_display() if absence else
               "No teacher" if lesson.teacher is None else "Teacher's account is deactivated")
        rows.append({
            **lesson_row(lesson), "period_name": lesson.period.name,
            "start_time": lesson.period.start_time.strftime("%H:%M"), "end_time": lesson.period.end_time.strftime("%H:%M"),
            "why": why,
            "cover": None if cover is None else {
                "teacher": cover.cover_teacher_id, "teacher_name": cover.cover_teacher.name if cover.cover_teacher else "",
                "note": cover.note, "assigned_by_name": cover.assigned_by_name},
            "free": free_staff(school, day, lesson.period_id, away, busy),
        })
    absent = [{"teacher": a.teacher_id, "name": a.teacher.name, "reason": a.get_reason_display(),
               "all_day": a.teacher_id in away and away[a.teacher_id] is None} for a in reasons.values()]
    return {"date": day, "day_name": DAY_NAMES[day.isoweekday()], "school_day": True,
            "absent": sorted(absent, key=lambda a: a["name"]), "lessons": rows,
            "covered": sum(1 for r in rows if r["cover"]), "total": len(rows)}


def arrange(lesson, day, cover_teacher, note, actor):
    """Set (or change) who covers `lesson` on `day`. Raises ValueError with a sentence if it can't."""
    if day.isoweekday() != lesson.day:
        raise ValueError(f"{lesson.school_class.name} {lesson.label} isn't on {DAY_NAMES[day.isoweekday()]}s.")
    away = absent_on(lesson.school, day)
    if not needs_cover(lesson, day, away):
        raise ValueError("This lesson's teacher isn't away that day, so it doesn't need cover.")
    if cover_teacher is not None:
        busy = _busy(lesson.school, day)
        existing = CoverAssignment.objects.filter(lesson=lesson, date=day).first()
        if existing and existing.cover_teacher_id == cover_teacher.id:
            busy.discard((cover_teacher.id, lesson.period_id))
        if (cover_teacher.id, lesson.period_id) in busy or _is_away(away, cover_teacher.id, lesson.period_id):
            raise ValueError(f"{cover_teacher.name} isn't free in {lesson.period.name}.")
    cover, _ = CoverAssignment.objects.update_or_create(
        lesson=lesson, date=day, defaults={"school": lesson.school, "cover_teacher": cover_teacher,
                                           "note": note[:200], "assigned_by_name": display_name(actor)})
    who = cover_teacher.name if cover_teacher else "no one (supervised another way)"
    log_activity(school=lesson.school, actor=actor, action="timetable.cover",
                 summary=f"Cover: {who} for {lesson.school_class.name} {lesson.label} "
                         f"({DAY_NAMES[lesson.day]} {day.isoformat()}, {lesson.period.name})")
    return cover


def my_cover(profile, day):
    """The cover lessons `profile` is taking on `day`, as rows like their own lessons."""
    rows = []
    for c in CoverAssignment.objects.filter(cover_teacher=profile, date=day).select_related(
            "lesson__school_class", "lesson__subject", "lesson__teacher", "lesson__room", "lesson__period"):
        lesson = c.lesson
        rows.append({**lesson_row(lesson), "cover": True, "cover_for": lesson.teacher.name if lesson.teacher else "",
                     "note": c.note, "start_time": lesson.period.start_time.strftime("%H:%M"),
                     "end_time": lesson.period.end_time.strftime("%H:%M"), "period_name": lesson.period.name})
    return rows
