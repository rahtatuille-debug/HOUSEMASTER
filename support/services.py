"""
Warning signs and suggestions for students who may need support.

HouseMaster only suggests: each sign below is checked against limits the
school sets (School.support_*), and a teacher confirms or dismisses every
suggestion. A student isn't suggested again in a term once a concern for
that term exists (open, resolved or dismissed), or while one is open.
"""
from collections import Counter, defaultdict

from django.db.models import Q

from attendance.models import AttendanceRecord

from .models import SupportConcern

REASONS = {
    "low_average": "Low average",
    "big_drop": "Average dropped",
    "poor_attendance": "Low attendance",
}


def _num(value):
    return f"{value:g}"


def _attendance_rates(student_ids, term):
    """{student: % of recorded days attended (present or late)} within the term's dates."""
    if not (term.start_date and term.end_date):
        return {}
    counts = defaultdict(Counter)
    for sid, status in AttendanceRecord.objects.filter(
        student_id__in=student_ids, date__gte=term.start_date, date__lte=term.end_date,
    ).values_list("student_id", "status"):
        counts[sid][status] += 1
    return {sid: round((c["present"] + c["late"]) / sum(c.values()) * 100, 1) for sid, c in counts.items() if c}


def warning_signs(data, term, student_ids):
    """{student: [{code, label}]} for the students showing a warning sign this term. `data` is SchoolGrades."""
    if term is None:
        return {}
    school = data.school
    graded = data.graded_terms
    previous = graded[graded.index(term) - 1] if term in graded and graded.index(term) > 0 else None
    rates = _attendance_rates(student_ids, term)
    found = {}
    for sid in student_ids:
        reasons = []
        average = data.student_average(sid, term.id)
        if average is not None and average < school.support_pass_mark:
            reasons.append({"code": "low_average", "label":
                            f"Average {_num(average)}% in {term.name}, below the pass mark of "
                            f"{school.support_pass_mark}%"})
        before = data.student_average(sid, previous.id) if previous else None
        if average is not None and before is not None and before - average >= school.support_drop_points:
            reasons.append({"code": "big_drop", "label":
                            f"Average fell {_num(round(before - average, 1))} points since {previous.name} "
                            f"({_num(before)}% to {_num(average)}%)"})
        rate = rates.get(sid)
        if rate is not None and rate < school.support_attendance_min:
            reasons.append({"code": "poor_attendance", "label":
                            f"Attended {_num(rate)}% of days in {term.name} (below {school.support_attendance_min}%)"})
        if reasons:
            found[sid] = reasons
    return found


def handled(student_ids, term):
    """Students who shouldn't be suggested: a concern is open, or one already exists for this term."""
    query = Q(status=SupportConcern.Status.OPEN)
    if term is not None:
        query |= Q(term=term)
    return set(SupportConcern.objects.filter(query, student_id__in=student_ids).values_list("student_id", flat=True))


def suggestions(data, term, student_ids):
    """{student: reasons} for students showing warning signs who haven't been looked at yet."""
    signs = warning_signs(data, term, student_ids)
    done = handled(list(signs), term)
    return {sid: reasons for sid, reasons in signs.items() if sid not in done}


def status_for(data, term, student_ids):
    """{student: "open" | "suggested"} for marking students in lists."""
    open_ids = set(SupportConcern.objects.filter(student_id__in=student_ids, status=SupportConcern.Status.OPEN)
                   .values_list("student_id", flat=True))
    out = {sid: "open" for sid in open_ids}
    for sid in suggestions(data, term, [s for s in student_ids if s not in open_ids]):
        out[sid] = "suggested"
    return out


def parent_view(student):
    """What a parent sees: the open concern's reasons, note and plan (no review date), or None."""
    concern = student.support_concerns.filter(status=SupportConcern.Status.OPEN).first()
    if concern is None:
        return None
    return {
        "id": concern.id, "reasons": concern.reasons, "note": concern.note, "support_plan": concern.support_plan,
        "created_at": concern.created_at, "created_by_name": concern.created_by_name,
    }


def notify_parents(concern, actor):
    """A short email to the student's parents; the details stay in HouseMaster."""
    from django.utils import timezone

    from guardians.models import Guardian
    from guardians.notifications import _footer, send_after_commit

    student = concern.student
    school = student.school
    parents = (Guardian.objects.filter(students=student, email_notifications=True, user__is_active=True)
               .exclude(user__email="").select_related("user"))
    messages = [(
        f"A note from {school.name} about {student.first_name}",
        f"Dear {g.name},\n\n{school.name} has added a note about {student.first_name} {student.last_name}'s "
        "progress, with how the school will support them and how you can help at home." + _footer(school),
        g.user.email,
    ) for g in parents]
    if not messages:
        return

    def done(sent, attempted):
        SupportConcern.objects.filter(pk=concern.pk).update(parents_notified_at=timezone.now())

    send_after_commit(messages, on_done=done)
