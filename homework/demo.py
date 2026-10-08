"""Homework for a demo school's classes, some already recorded (never real data)."""
import random
from datetime import timedelta

from accounts.models import TeachingAssignment
from students.localtime import school_localdate

from .models import Assignment, HomeworkRecord
from .services import students_for

TITLES = ["Chapter review questions", "Practice worksheet", "Short essay", "Revision for Friday's quiz",
          "Research task", "Problem set", "Reading and summary", "Vocabulary list"]


def fill_demo(school, seed=11, per_class=2):
    """Returns how many pieces of homework were added (two subjects in every class)."""
    if Assignment.objects.filter(school=school).exists():
        return 0
    rng = random.Random(seed)
    today = school_localdate(school)
    pairs, per = [], {}
    for t in (TeachingAssignment.objects.filter(teacher__school=school, subject__isnull=False)
              .select_related("teacher__user", "school_class", "subject").order_by("school_class_id", "id")):
        if per.get(t.school_class_id, 0) < per_class:
            per[t.school_class_id] = per.get(t.school_class_id, 0) + 1
            pairs.append(t)
    added = 0
    for t in pairs:
        for days in (-6, 4):
            a = Assignment.objects.create(
                school=school, school_class=t.school_class, subject=t.subject, title=rng.choice(TITLES),
                instructions="Complete it in your exercise book and bring it to the next lesson.",
                set_on=today + timedelta(days=days - 5), due_date=today + timedelta(days=days), out_of=rng.choice((10, 20, None)),
                set_by=t.teacher.user, set_by_name=t.teacher.name)
            added += 1
            if days < 0:  # past: mostly recorded
                HomeworkRecord.objects.bulk_create([HomeworkRecord(
                    assignment=a, student=s, status=rng.choices(("handed_in", "late", "missing"), (80, 12, 8))[0],
                    mark=(rng.randint(a.out_of // 2, a.out_of) if a.out_of else None)) for s in students_for(a)])
    return added
