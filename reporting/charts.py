"""
Five more performance graphs (P-1 … P-5), built from the same numbers as the rest of the Performance page.

- P-1 subject trends: each subject's result every term (reporting.analytics.SchoolGrades, so a subject's result is
  the same weighted mean the report card uses), with the class's result beside it when enough classmates have marks.
  P-5 (the strengths radar) draws one term of these, so it needs no endpoint of its own.
- P-2 assessment types: the student's mean in each of the school's own assessment types. Weights are shown, never
  applied again.
- P-3 marks within a term: every mark, by the date it was recorded on the school's clock (a mark has no
  assessment date of its own).
- P-4 rank over time: the overall position each term from reporting.rankings, as the ranked tables show it.

Comparisons are averages only and are left out when fewer than MIN_COMPARE_STUDENTS students have marks, so a
comparison never stands for one or two identifiable children. Parents get these graphs through
guardian_charts, which gives them only what their child's pages already show.
"""
from collections import defaultdict

from gradebook.models import Grade
from students.presets import student_section

from .analytics import _grading, _mean

# The fewest students with marks behind any class or group comparison (a class average, a class line). Below it
# the comparison is left out. See docs/CHARTS.md. The owner may want to change it.
MIN_COMPARE_STUDENTS = 5

CHARTS = ("subject_trends",)


def _terms(data):
    return [{"id": t.id, "name": t.name} for t in data.graded_terms]


def _compare(values):
    """The mean of other students' values, or None when too few have one."""
    values = [v for v in values if v is not None]
    return _mean(values) if len(values) >= MIN_COMPARE_STUDENTS else None


# P-1 -------------------------------------------------------------------------------------------------------------

def student_subject_trends(data, student):
    sid = student.id
    klass = student.school_class
    classmates = data.in_class(klass.id) if klass else []
    subjects = sorted({s for t in data.graded_terms for s in data.marks.get((sid, t.id), {})})
    lines = []
    for subject in subjects:
        points = []
        for t in data.graded_terms:
            mine = data.student_subject(sid, t.id, subject) if subject in data.marks.get((sid, t.id), {}) else None
            others = [data.student_subject(m, t.id, subject) for m in classmates
                      if subject in data.marks.get((m, t.id), {})]
            points.append({"term": t.name, "term_id": t.id, "student": mine, "class": _compare(others)})
        lines.append({"subject": subject, "points": points})
    system, scale = student_section(student)
    return {"chart": "subject_trends", "scope": "student", "name": f"{student.first_name} {student.last_name}",
            "class_name": klass.name if klass else None, "terms": _terms(data), "subjects": lines,
            "compare": {"min_students": MIN_COMPARE_STUDENTS}, "grading": _grading(system, scale)}


def group_subject_trends(data, scope, name, student_ids, grading):
    per_term = {t.id: data.group_subjects(student_ids, t.id) for t in data.graded_terms}
    subjects = sorted({s for values in per_term.values() for s in values})
    lines = [{"subject": subject, "points": [{"term": t.name, "term_id": t.id, "average": per_term[t.id].get(subject)}
                                            for t in data.graded_terms]} for subject in subjects]
    return {"chart": "subject_trends", "scope": scope, "name": name, "terms": _terms(data), "subjects": lines,
            "grading": grading}


# Parents ---------------------------------------------------------------------------------------------------------

def guardian_charts(student, chart, term_id=None):
    """
    A parent's (or the student's own) view, never wider than what their pages already show: subject results only
    for terms with a finalized report (as the term summary), no class or other comparisons (withheld from parents
    everywhere), marks without assessment types (the marks list has none), and positions only where the finalized
    8-4-4 report card already shows them. None for a chart parents don't get.
    """
    from gradebook.weighting import school_weights, subject_percents
    from reporting.models import StudentReport

    finalized = {r.term_id: r for r in StudentReport.objects.filter(student=student, status="finalized")
                 .with_content().select_related("term")}
    terms = sorted({r.term for r in finalized.values()}, key=lambda t: (t.start_date is None, t.start_date, t.id))
    system, scale = student_section(student)
    name = f"{student.first_name} {student.last_name}"
    if chart == "subject_trends":
        grades = Grade.objects.filter(student=student, term_id__in=[t.id for t in terms], max_score__gt=0) \
            .select_related("subject")
        results = subject_percents(grades, school_weights(student.school), key=lambda g: g.subject.name)
        per_term = {t.id: results.get((student.id, t.id), {}) for t in terms}
        subjects = sorted({s for values in per_term.values() for s in values})
        lines = [{"subject": s, "points": [{"term": t.name, "term_id": t.id,
                                            "student": round(per_term[t.id][s], 1) if s in per_term[t.id] else None}
                                           for t in terms]} for s in subjects]
        return {"chart": chart, "scope": "student", "name": name, "terms": [{"id": t.id, "name": t.name} for t in terms],
                "subjects": lines, "grading": _grading(system, scale)}
    return None
