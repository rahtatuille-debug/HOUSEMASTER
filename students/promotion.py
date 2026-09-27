"""
End of year: move every student in a class to their next class in one step.

The admin maps each class to where its students go (another class, or
"leaving", which deactivates them and keeps their history). Classes not in
the plan stay as they are. Every student's destination is worked out from
the classes they're in *before* anyone moves, so swaps and chains
(7A -> 8A while 8A -> 9A) are safe.
"""
from datetime import date

from django.db import transaction
from rest_framework.exceptions import ValidationError

from activity.services import log_activity

from .models import SchoolClass, Student


def plan_promotion(school, moves):
    """
    `moves` is a list of {"from_class": id, "to_class": id or None}. Returns
    the validated plan: [(from_class, to_class or None, [students])].
    """
    classes = {c.id: c for c in SchoolClass.objects.filter(year_group__school=school).select_related("year_group")}
    plan, seen = [], set()
    for move in moves:
        try:
            from_id = int(move["from_class"])
            to_id = move.get("to_class")
            to_id = int(to_id) if to_id not in (None, "") else None
        except (KeyError, TypeError, ValueError):
            raise ValidationError("Each move needs a from_class and a to_class (or null for leaving).")
        if from_id not in classes or (to_id is not None and to_id not in classes):
            raise ValidationError("Class not found.")
        if from_id in seen:
            raise ValidationError(f"{classes[from_id].name} appears more than once.")
        if from_id == to_id:
            continue  # staying put
        seen.add(from_id)
        students = list(Student.objects.filter(school=school, school_class_id=from_id, is_active=True))
        plan.append((classes[from_id], classes[to_id] if to_id else None, students))
    return plan


def summarize(plan):
    return [
        {"from_class": f.id, "from_name": f.name, "to_class": t.id if t else None,
         "to_name": t.name if t else ("Graduating" if f.year_group.is_final else "Leaving school"),
         "students": len(s)}
        for f, t, s in plan
    ]


@transaction.atomic
def apply_promotion(school, actor, plan):
    for from_class, to_class, students in plan:
        ids = [s.id for s in students]
        if to_class is None and from_class.year_group.is_final:
            # Leaving from the final year is graduating; their records stay.
            Student.objects.filter(id__in=ids).update(is_active=False, graduated_on=date.today())
            summary = f"Graduated {len(ids)} students from {from_class.name}"
        elif to_class is None:
            Student.objects.filter(id__in=ids).update(is_active=False)
            summary = f"Marked {len(ids)} students in {from_class.name} as leaving school (deactivated)"
        else:
            Student.objects.filter(id__in=ids).update(school_class=to_class)
            summary = f"Moved {len(ids)} students from {from_class.name} to {to_class.name}"
        if ids:
            log_activity(school=school, actor=actor, action="student.promoted", summary=summary,
                         from_class=from_class.id, to_class=to_class.id if to_class else None, students=ids)
    moved = sum(len(s) for _, t, s in plan if t)
    left = sum(len(s) for _, t, s in plan if not t)
    log_activity(school=school, actor=actor, action="school.year_end",
                 summary=f"Moved students up a year: {moved} moved, {left} leaving")
