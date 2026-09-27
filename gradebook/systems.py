"""
How each education system summarises a student's term, for report cards,
the student page and parents:

* CBC: a level per learning area (EE/ME/AE/BE or the 8-level scale). No
  positions: CBC doesn't rank learners.
* 8-4-4: KCSE points per subject (A = 12 down to E = 1), total and mean
  points, a mean grade, and position in the stream and in the form. The mean
  covers every subject the student sat this term (schools that apply the
  KNEC "best seven" rule for KCSE can still read it off the subject list).
* British: the attainment grade per subject, with the teacher's effort and
  target grades.
* IB: the MYP 1 to 7 grade worked out from criteria A to D (each 0 to 8)
  when all four are entered, otherwise from the percentage.
* American: a GPA on a 4.0 scale, weighted by each course's credits, and
  honor roll.

A subject's percentage for the term is the mean of its marks, as elsewhere.
"""
from collections import defaultdict

from .levels import level_for
from .models import Grade, SubjectReport

KCSE_POINTS = {"A": 12, "A-": 11, "B+": 10, "B": 9, "B-": 8, "C+": 7, "C": 6, "C-": 5, "D+": 4, "D": 3,
               "D-": 2, "E": 1}
KCSE_BY_POINTS = {points: grade for grade, points in KCSE_POINTS.items()}
GPA_POINTS = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
# Sum of MYP criteria A-D (out of 32) -> 1 to 7, the IB's published boundaries.
MYP_BOUNDARIES = [(28, 7), (24, 6), (19, 5), (15, 4), (10, 3), (6, 2), (0, 1)]
CRITERIA = ["A", "B", "C", "D"]


def mean_grade(mean_points):
    """KCSE mean grade for a mean of subject points, rounded to the nearest point."""
    if mean_points is None:
        return ""
    return KCSE_BY_POINTS[max(1, min(12, int(mean_points + 0.5)))]


def myp_grade(criteria):
    """The MYP 1-7 grade from criteria A-D, or None unless all four are entered (0-8 each)."""
    try:
        values = [int(criteria[c]) for c in CRITERIA]
    except (KeyError, TypeError, ValueError):
        return None
    if any(v < 0 or v > 8 for v in values):
        return None
    total = sum(values)
    return next(grade for low, grade in MYP_BOUNDARIES if total >= low)


def honor_roll(gpa):
    if gpa is None:
        return ""
    return "High honor roll" if gpa >= 3.5 else "Honor roll" if gpa >= 3.0 else ""


def _subject_percents(student_ids, term):
    """{student_id: {subject: percent}} for the term, averaging a subject's marks."""
    marks = defaultdict(lambda: defaultdict(list))
    subjects = {}
    for g in Grade.objects.filter(student_id__in=student_ids, term=term).select_related("subject"):
        if g.max_score:
            marks[g.student_id][g.subject_id].append(float(g.score) / float(g.max_score) * 100)
            subjects[g.subject_id] = g.subject
    return {sid: {subjects[sub]: sum(v) / len(v) for sub, v in per.items()} for sid, per in marks.items()}


def _mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _kcse_totals(percents):
    points = [KCSE_POINTS[level_for(p, "kcse")] for p in percents.values()]
    mean = _mean(points)
    return (sum(points) if points else None), (round(mean, 3) if mean is not None else None), _mean(percents.values())


def _positions(student, term, system):
    """8-4-4 only: position in the stream and in the form, by mean points (then average mark)."""
    from students.models import Student

    klass = student.school_class
    if system != "844" or klass is None:
        return None
    form = list(Student.objects.filter(school=student.school, is_active=True,
                                       school_class__year_group_id=klass.year_group_id)
                .values_list("id", "school_class_id"))
    percents = _subject_percents([sid for sid, _ in form], term)
    scores = {}
    for sid, _class_id in form:
        if percents.get(sid):
            _total, mean, avg = _kcse_totals(percents[sid])
            scores[sid] = (mean, avg)
    if student.id not in scores:
        return None

    def place(ids):
        ranked = sorted((scores[i] for i in ids if i in scores), reverse=True)
        return {"position": ranked.index(scores[student.id]) + 1, "of": len(ranked)}

    return {"stream": place([sid for sid, cid in form if cid == klass.id]), "form": place([sid for sid, _ in form])}


def term_summary(student, term):
    """Everything a report card shows about the student's results this term, for their school's system."""
    school = student.school
    system, scale = school.education_system, school.grading_scale
    percents = _subject_percents([student.id], term).get(student.id, {})
    entries = {r.subject_id: r for r in SubjectReport.objects.filter(student=student, term=term).select_related("subject")}
    subjects = sorted(set(percents) | {r.subject for r in entries.values()}, key=lambda s: s.name)

    rows = []
    for subject in subjects:
        percent = percents.get(subject)
        entry = entries.get(subject.id)
        row = {
            "subject_id": subject.id, "subject": subject.name,
            "percent": round(percent, 1) if percent is not None else None,
            "level": level_for(percent, scale),
            "comment": entry.comment if entry else "", "effort": entry.effort if entry else "",
            "target": entry.target if entry else "",
        }
        if system == "844":
            code = level_for(percent, "kcse")
            row.update(kcse_grade=code, points=KCSE_POINTS.get(code))
        elif system == "american":
            letter = level_for(percent, "american")
            row.update(letter=letter, gpa_points=GPA_POINTS.get(letter), credits=float(subject.credits))
        elif system == "ib":
            criteria = entry.criteria if entry else {}
            row.update(criteria=criteria, ib_grade=myp_grade(criteria) or (int(level_for(percent, "ib"))
                                                                       if percent is not None else None))
        rows.append(row)

    summary = {"system": system, "subjects": rows}
    average = _mean(percents.values())
    summary["average"] = round(average, 1) if average is not None else None
    summary["average_level"] = level_for(average, scale)
    if system == "844" and percents:
        total, mean, _avg = _kcse_totals(percents)
        summary.update(total_points=total, mean_points=round(mean, 2), mean_grade=mean_grade(mean),
                       total_marks=round(sum(percents.values())), positions=_positions(student, term, system))
    elif system == "american":
        graded = [r for r in rows if r["gpa_points"] is not None]
        credits = sum(r["credits"] for r in graded)
        gpa = round(sum(r["gpa_points"] * r["credits"] for r in graded) / credits, 2) if credits else None
        summary.update(gpa=gpa, honor_roll=honor_roll(gpa), credits=credits)
    elif system == "ib":
        grades = [r["ib_grade"] for r in rows if r["ib_grade"] is not None]
        summary.update(ib_total=sum(grades) if grades else None)
    return summary


# Extra ratings some report cards carry, entered on the report itself.
REPORT_EXTRAS = {
    "cbc": [
        {"key": "competencies", "title": "Core competencies", "ratings": ["EE", "ME", "AE", "BE"], "items": [
            "Communication and collaboration", "Critical thinking and problem solving", "Creativity and imagination",
            "Citizenship", "Digital literacy", "Learning to learn", "Self-efficacy"]},
        {"key": "values", "title": "Values", "ratings": ["EE", "ME", "AE", "BE"], "items": [
            "Love", "Responsibility", "Respect", "Unity", "Peace", "Patriotism", "Social justice", "Integrity"]},
    ],
    "ib": [
        {"key": "atl", "title": "Approaches to learning", "ratings": ["E", "P", "L", "N"],
         "rating_names": {"E": "Expert", "P": "Practitioner", "L": "Learner", "N": "Novice"},
         "items": ["Thinking skills", "Communication skills", "Social skills", "Self-management skills",
                   "Research skills"]},
    ],
}
# What each system records per subject besides a comment.
SUBJECT_FIELDS = {"british": ["effort", "target"], "ib": ["criteria"]}


def clean_extra(system, extra):
    """Keep only the ratings this system's report card has, with allowed values. Raises ValueError otherwise."""
    if not isinstance(extra, dict):
        raise ValueError("extra must be an object")
    cleaned = {}
    for group in REPORT_EXTRAS.get(system, []):
        given = extra.get(group["key"]) or {}
        if not isinstance(given, dict):
            raise ValueError(f"{group['title']} must be an object")
        for item, rating in given.items():
            if item not in group["items"]:
                raise ValueError(f'"{item}" isn\'t one of the {group["title"].lower()}')
            if rating not in group["ratings"] + [""]:
                raise ValueError(f'"{rating}" isn\'t a rating for {item}')
        cleaned[group["key"]] = {k: v for k, v in given.items() if v}
    return cleaned
