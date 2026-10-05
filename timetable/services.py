"""Clash checks, week views and the standard school day for the timetable."""
from collections import defaultdict
from datetime import datetime, time, timedelta

from django.db.models import Q

from accounts.models import TeachingAssignment
from gradebook.models import StudentSubject
from students.models import Student

from .models import DAY_NAMES, Lesson, Period, SchoolWeek


def school_days(school):
    week = SchoolWeek.objects.filter(school=school).first()
    return week.day_numbers() if week else [1, 2, 3, 4, 5]


def _takers(school_class, subject):
    """The class's active students who take a subject, or None for "everyone" (core subjects, assemblies)."""
    if subject is None or not subject.is_elective:
        return None
    return set(StudentSubject.objects.filter(subject=subject, student__school_class=school_class,
                                             student__is_active=True).values_list("student_id", flat=True))


def _class_overlap(school_class, a, b):
    """How many of the class's students would have to be in both lessons at once (None: everyone)."""
    first, second = _takers(school_class, a), _takers(school_class, b)
    if first is None or second is None:
        return None
    return len(first & second)


def clashes(lesson):
    """What stops this lesson going in its slot, as sentences for the person placing it."""
    problems = []
    if lesson.period.is_break:
        problems.append(f"{lesson.period.name} is a break, so it can't hold a lesson.")
    same_slot = Lesson.objects.filter(school=lesson.school, day=lesson.day, period=lesson.period) \
        .select_related("school_class", "subject", "teacher", "room")
    if lesson.pk:
        same_slot = same_slot.exclude(pk=lesson.pk)
    when = f"{DAY_NAMES[lesson.day]} {lesson.period.name}"
    for other in same_slot:
        if lesson.teacher_id and other.teacher_id == lesson.teacher_id:
            problems.append(f"{other.teacher.name} already teaches {other.school_class.name} {other.label} "
                            f"on {when}.")
        if lesson.room_id and other.room_id == lesson.room_id:
            problems.append(f"{other.room.name} is already used by {other.school_class.name} {other.label} "
                            f"on {when}.")
        if other.school_class_id == lesson.school_class_id:
            shared = _class_overlap(lesson.school_class, lesson.subject, other.subject)
            if shared is None:
                problems.append(f"{other.school_class.name} already has {other.label} on {when}.")
            elif shared:
                problems.append(f"{shared} student{'s' if shared != 1 else ''} in {other.school_class.name} take "
                                f"both {lesson.label} and {other.label}, which is already on {when}.")
    return problems


def unstaffed(school):
    """Lessons with no teacher, or whose teacher's account is deactivated, in timetable order."""
    lessons = Lesson.objects.filter(school=school).filter(Q(teacher__isnull=True) | Q(teacher__user__is_active=False)) \
        .select_related("school_class", "subject", "teacher__user", "room", "period")
    return [unstaffed_row(lesson) for lesson in lessons]


def unstaffed_row(lesson):
    row = lesson_row(lesson)
    if lesson.teacher is not None and not lesson.teacher.user.is_active:
        row["teacher_name"] = f"{lesson.teacher.name} (inactive)"
    return {**row, "day_name": DAY_NAMES[lesson.day], "period_name": lesson.period.name}


def class_clashes(school_class):
    """Clashes in a class's timetable as it stands now, e.g. after students change their options: two lessons in
    one slot that some of the class's students both take. Sentences for the person who made the change."""
    by_slot = {}
    for lesson in Lesson.objects.filter(school_class=school_class).select_related("subject", "period", "school_class"):
        by_slot.setdefault((lesson.day, lesson.period_id), []).append(lesson)
    found = []
    for lessons in by_slot.values():
        for i, first in enumerate(lessons):
            for second in lessons[i + 1:]:
                shared = _class_overlap(school_class, first.subject, second.subject)
                when = f"{DAY_NAMES[first.day]} {first.period.name}"
                if shared is None:
                    found.append(f"{school_class.name} has both {first.label} and {second.label} on {when}.")
                elif shared:
                    found.append(f"{shared} student{'s' if shared != 1 else ''} in {school_class.name} now take both "
                                 f"{first.label} and {second.label}, which are both on {when}.")
    return found


def default_teacher(school_class, subject):
    """Who teaches this subject to this class (Staff page assignments), or the class teacher."""
    found = TeachingAssignment.objects.filter(school_class=school_class, subject=subject).first() if subject else None
    found = found or TeachingAssignment.objects.filter(school_class=school_class, subject__isnull=True).first()
    return found.teacher if found else None


def lesson_row(lesson):
    return {
        "id": lesson.id, "day": lesson.day, "period": lesson.period_id,
        "school_class": lesson.school_class_id, "class_name": lesson.school_class.name,
        "subject": lesson.subject_id, "title": lesson.title, "label": lesson.label,
        "teacher": lesson.teacher_id, "teacher_name": lesson.teacher.name if lesson.teacher else "",
        "room": lesson.room_id, "room_name": lesson.room.name if lesson.room else "",
    }


def week(school, lessons):
    """A week grid: the school's days and periods, and the lessons in it."""
    days = school_days(school)
    periods = list(Period.objects.filter(school=school))
    lessons = lessons.filter(day__in=days).select_related("school_class", "subject", "teacher", "room", "period")
    return {
        "days": [{"day": d, "name": DAY_NAMES[d]} for d in days],
        "periods": [{"id": p.id, "name": p.name, "start_time": p.start_time.strftime("%H:%M"),
                     "end_time": p.end_time.strftime("%H:%M"), "is_break": p.is_break} for p in periods],
        "lessons": [lesson_row(lesson) for lesson in lessons],
    }


def student_lessons(student):
    """The lessons a student goes to: their class's lessons in core subjects and the electives they chose."""
    if not student.school_class_id:
        return Lesson.objects.none()
    chosen = StudentSubject.objects.filter(student=student).values_list("subject_id", flat=True)
    return Lesson.objects.filter(school_class_id=student.school_class_id).filter(
        Q(subject__isnull=True) | Q(subject__is_elective=False) | Q(subject_id__in=chosen))


def standard_day(school, start="08:00", lesson_minutes=40, lessons=8, breaks=None):
    """Replace the periods with a regular day: `lessons` lessons of `lesson_minutes`, with breaks after some.

    breaks: [{"after": 2, "minutes": 20, "name": "Break"}, ...]. Refuses (ValueError) once lessons exist."""
    if Lesson.objects.filter(school=school).exists():
        raise ValueError("The timetable already has lessons. Change the periods one by one instead.")
    if not 1 <= int(lessons) <= 14 or not 10 <= int(lesson_minutes) <= 120:
        raise ValueError("Choose 1 to 14 lessons of 10 to 120 minutes.")
    after = {int(b["after"]): b for b in (breaks or [])}
    clock = datetime.combine(datetime.today(), time.fromisoformat(start))
    rows = []
    for n in range(1, int(lessons) + 1):
        end = clock + timedelta(minutes=int(lesson_minutes))
        rows.append(Period(school=school, name=f"Lesson {n}", start_time=clock.time(), end_time=end.time()))
        clock = end
        if n in after and n != int(lessons):
            gap = int(after[n].get("minutes") or 20)
            end = clock + timedelta(minutes=gap)
            rows.append(Period(school=school, name=after[n].get("name") or "Break", start_time=clock.time(),
                               end_time=end.time(), is_break=True))
            clock = end
    if clock.date() != datetime.today().date():
        raise ValueError("That day runs past midnight.")
    Period.objects.filter(school=school).delete()
    Period.objects.bulk_create(rows)
    return rows


# --- demo schools -----------------------------------------------------------

def lessons_per_week(subject_name, year_group_name):
    """A plausible number of lessons a week for a subject, for demo timetables."""
    name = subject_name.lower()
    sixth = any(w in year_group_name for w in ("12", "13", "DP"))
    if sixth:
        return 4
    if any(w in name for w in ("english", "math", "kiswahili", "language and literature")):
        return 4
    if any(w in name for w in ("biology", "chemistry", "physics", "science")):
        return 3
    return 2


def fill_demo(school, rooms=0):
    """Build a timetable for a demo school from its teaching assignments, avoiding every clash.

    Places what fits (a few lessons may not), creates a standard day if there are no periods, and
    returns how many lessons were placed."""
    if not Period.objects.filter(school=school).exists():
        standard_day(school, breaks=[{"after": 2, "minutes": 20, "name": "Break"},
                                     {"after": 5, "minutes": 60, "name": "Lunch"}])
    days = school_days(school)
    slots = [(d, p) for p in Period.objects.filter(school=school, is_break=False) for d in days]
    room_list = []
    if rooms:
        from .models import Room

        Room.objects.bulk_create([Room(school=school, name=f"Room {n}") for n in range(1, rooms + 1)],
                                 ignore_conflicts=True)
        room_list = list(Room.objects.filter(school=school))
    teacher_busy, room_busy, home_rooms = set(), set(), {}
    class_slot = defaultdict(list)  # (class, day, period) -> [set of students or None]
    created = []
    # Who takes each elective in each class.
    takers = defaultdict(set)
    for sid, subject_id, class_id in StudentSubject.objects.filter(
            student__school=school, student__is_active=True).values_list(
            "student_id", "subject_id", "student__school_class_id"):
        takers[(class_id, subject_id)].add(sid)
    class_size = defaultdict(int)
    for class_id in Student.objects.filter(school=school, is_active=True).values_list("school_class_id", flat=True):
        class_size[class_id] += 1

    jobs = _demo_jobs(school)
    for i, (school_class, subject, teacher) in enumerate(jobs):
        group = None if not subject.is_elective else takers.get((school_class.id, subject.id), set())
        if group is not None and not group:
            continue  # nobody in this class takes it
        need = lessons_per_week(subject.name, school_class.year_group.name)
        placed_days = set()
        start = (i * 7) % len(slots)
        # First pass spreads the subject over the week; the second fills any free slot, so a class can
        # have the same subject more than once a day when that's what fits.
        for k in range(2 * len(slots)):
            if need == 0:
                break
            day, period = slots[(start + k) % len(slots)]
            if k < len(slots) and day in placed_days:
                continue
            if teacher and (teacher.id, day, period.id) in teacher_busy:
                continue
            here = class_slot[(school_class.id, day, period.id)]
            if any(g is None or group is None or g & group for g in here):
                continue
            room = None
            if room_list:
                # The class's own room when it's free, otherwise the first free one.
                home = room_list[home_rooms.setdefault(school_class.id, len(home_rooms)) % len(room_list)]
                for r in [home, *room_list]:
                    if (r.id, day, period.id) not in room_busy:
                        room = r
                        break
            created.append(Lesson(school=school, school_class=school_class, subject=subject, teacher=teacher,
                                  room=room, day=day, period=period))
            if teacher:
                teacher_busy.add((teacher.id, day, period.id))
            if room:
                room_busy.add((room.id, day, period.id))
            here.append(group)
            placed_days.add(day)
            need -= 1
    Lesson.objects.bulk_create(created, batch_size=2000)
    return len(created)


def _demo_jobs(school):
    """(class, subject, teacher) for every subject each class is taught: the subject's teacher from the Staff
    page, or else the class teacher for subjects the class has marks in."""
    from gradebook.models import Grade
    from students.models import SchoolClass

    specific, class_teacher = {}, {}
    for a in TeachingAssignment.objects.filter(school_class__year_group__school=school).select_related("teacher"):
        if a.subject_id:
            specific.setdefault((a.school_class_id, a.subject_id), a.teacher)
        else:
            class_teacher.setdefault(a.school_class_id, a.teacher)
    marked = set(Grade.objects.filter(student__school=school, student__is_active=True)
                 .values_list("student__school_class_id", "subject_id").distinct())
    subjects = {s.id: s for s in school.subjects.all()}
    jobs = []
    for klass in SchoolClass.objects.filter(year_group__school=school).select_related("year_group") \
            .order_by("year_group__order", "name"):
        wanted = {sid for (cid, sid) in specific if cid == klass.id} | {sid for (cid, sid) in marked if cid == klass.id}
        for sid in sorted(wanted, key=lambda i: subjects[i].name):
            teacher = specific.get((klass.id, sid)) or class_teacher.get(klass.id)
            jobs.append((klass, subjects[sid], teacher))
    return jobs
