"""
Turning a student's marks into a subject's term result.

Each mark is a percentage. Marks of the same assessment type are averaged,
then the types are combined by their weights (e.g. CAT 30, End-term exam
70). Only the types that actually have marks count, rescaled to 100%, so a
subject with only CATs so far isn't dragged down by a missing exam. Marks
with no type count as one more type with the average weight of the others.
A school with no assessment types gets a plain average, as before.

Every screen, report card and export uses these functions so they agree.
"""
from collections import defaultdict

from .models import AssessmentType, Grade


def school_weights(school):
    return {t.id: float(t.weight) for t in AssessmentType.objects.filter(school=school)}


def subject_percent(marks, weights):
    """marks: [(percent, assessment_type_id or None)] for one subject. Returns the weighted percent or None."""
    groups = defaultdict(list)
    for percent, type_id in marks:
        if percent is not None:
            groups[type_id if type_id in weights else None].append(percent)
    if not groups:
        return None
    means = {t: sum(v) / len(v) for t, v in groups.items()}
    known = [weights[t] for t in means if t is not None]
    fallback = sum(known) / len(known) if known else 1.0
    shares = {t: (weights[t] if t is not None else fallback) for t in means}
    total = sum(shares.values())
    if total <= 0:
        return sum(means.values()) / len(means)
    return sum(means[t] * shares[t] for t in means) / total


def percent(score, max_score):
    return float(score) / float(max_score) * 100 if max_score else None


def subject_percents(grades, weights, key=lambda g: g.subject):
    """{(student_id, term_id): {subject: percent}} from Grade objects."""
    marks = defaultdict(lambda: defaultdict(list))
    for g in grades:
        marks[(g.student_id, g.term_id)][key(g)].append((percent(g.score, g.max_score), g.assessment_type_id))
    return {k: {s: p for s, m in per.items() if (p := subject_percent(m, weights)) is not None}
            for k, per in marks.items()}


def student_average(per_subject):
    """A student's term average: the mean of their subject results."""
    values = [v for v in per_subject.values() if v is not None]
    return sum(values) / len(values) if values else None


def term_results(students, term, school):
    """{student_id: {subject: percent}} for these students' marks in the term."""
    grades = Grade.objects.filter(student__in=students, term=term).select_related("subject")
    return {sid: per for (sid, _t), per in subject_percents(grades, school_weights(school)).items()}
