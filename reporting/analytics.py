"""
Performance analytics for one student, a class, a year group, or the whole school.

Definitions, used everywhere so numbers always agree:
- a student's average for a term = the mean of their subject percentages
  (score / max score) that term;
- a group's average = the mean of its students' averages, so a student with
  many grades doesn't count more than one with few.
Only active students count towards group figures.
"""
from collections import defaultdict
from datetime import date

from gradebook.levels import SCALES, levels, school_sections
from students.presets import SHORT_NAMES, section_for, student_section
from gradebook.models import Grade, Term
from gradebook.weighting import school_weights, subject_percent
from students.models import SchoolClass, Student, YearGroup

from . import rankings

BANDS = [(0, 40, "Below 40%"), (40, 50, "40–49%"), (50, 60, "50–59%"), (60, 70, "60–69%"),
         (70, 80, "70–79%"), (80, 101, "80% and above")]


def _mean(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


class SchoolGrades:
    """Every active student's grades at a school, loaded once and averaged in memory."""

    def __init__(self, school):
        self.school = school
        self.scale = school.grading_scale
        self.terms = sorted(Term.objects.filter(school=school), key=lambda t: (t.start_date or date.min, t.id))
        self.students = {
            s.id: s for s in Student.objects.filter(school=school, is_active=True)
            .select_related("school", "school_class__year_group")
        }
        # (student, term) -> {subject: [(percent, assessment type), ...]}
        self.weights = school_weights(school)
        self.marks = defaultdict(lambda: defaultdict(list))
        for student_id, term_id, subject, section, score, max_score, type_id in Grade.objects.filter(
            student_id__in=self.students
        ).values_list("student_id", "term_id", "subject__name", "subject__education_system", "score", "max_score",
                      "assessment_type_id"):
            if max_score:
                # Each curriculum's subjects are separate, e.g. "Mathematics · British".
                subject = f"{subject} · {SHORT_NAMES.get(section, section)}" if section else subject
                self.marks[(student_id, term_id)][subject].append((float(score) / float(max_score) * 100, type_id))
        self.graded_terms = [t for t in self.terms if any(k[1] == t.id for k in self.marks)]

    def student_average(self, student_id, term_id):
        subjects = self.marks.get((student_id, term_id))
        return _mean([self.student_subject(student_id, term_id, s) for s in subjects]) if subjects else None

    def student_subject(self, student_id, term_id, subject):
        result = subject_percent(self.marks.get((student_id, term_id), {}).get(subject, []), self.weights)
        return round(result, 1) if result is not None else None

    def subject_percents(self, student_id, term_id):
        """{subject: unrounded percent} for ranking, so positions match the report card's."""
        marks = self.marks.get((student_id, term_id), {})
        out = {subject: subject_percent(m, self.weights) for subject, m in marks.items()}
        return {subject: p for subject, p in out.items() if p is not None}

    def group_average(self, student_ids, term_id):
        return _mean([self.student_average(s, term_id) for s in student_ids])

    def group_subjects(self, student_ids, term_id):
        per_subject = defaultdict(list)
        for s in student_ids:
            for subject in self.marks.get((s, term_id), {}):
                per_subject[subject].append(self.student_subject(s, term_id, subject))
        return {subject: _mean(values) for subject, values in per_subject.items()}

    def distribution(self, student_ids, term_id, scale=None):
        averages = [a for a in (self.student_average(s, term_id) for s in student_ids) if a is not None]
        return [
            {"band": label, "students": sum(1 for a in averages if low <= a < high)}
            for low, high, label in self.bands(scale)
        ]

    def section_of(self, student_id):
        return student_section(self.students[student_id])

    def bands(self, scale=None):
        """Schools with levels count students per level, lowest first; others use 10% bands."""
        scale = SCALES.get(scale or self.scale)
        if not scale:
            return BANDS
        lows = [low for low, _code, _name in scale]
        return [(low, lows[i - 1] if i else 101, code) for i, (low, code, _name) in enumerate(scale)][::-1]

    def in_class(self, class_id):
        return [s.id for s in self.students.values() if s.school_class_id == class_id]

    def in_year(self, year_id):
        return [s.id for s in self.students.values()
                if s.school_class_id and s.school_class.year_group_id == year_id]

    def everyone(self):
        return list(self.students)

    def term(self, term_id):
        """The requested term, or the latest term that has grades."""
        if term_id:
            for t in self.terms:
                if str(t.id) == str(term_id):
                    return t
        return self.graded_terms[-1] if self.graded_terms else None


def _terms(data):
    return [{"id": t.id, "name": t.name, "is_locked": t.is_locked} for t in data.graded_terms]


def _subject_rows(primary, compare, primary_key, compare_key):
    subjects = sorted(set(primary) | set(compare))
    return [{"subject": s, primary_key: primary.get(s), compare_key: compare.get(s)} for s in subjects]


def _student_rows(data, student_ids, term, visible_ids):
    """
    Each visible student's average this term, change since the previous graded
    term, and positions (reporting.rankings): overall, most improved and in
    each subject. Positions count every student in the group, also those the
    viewer can't see by name, and only within the same curriculum. CBC
    students get no positions.
    """
    if term is None:
        return []
    index = data.graded_terms.index(term) if term in data.graded_terms else -1
    previous = data.graded_terms[index - 1] if index > 0 else None
    system = {sid: rankings.effective_system(*data.section_of(sid)) for sid in student_ids}
    raw = {sid: data.subject_percents(sid, term.id) for sid in student_ids}
    average = {sid: data.student_average(sid, term.id) for sid in student_ids}
    before = {sid: data.student_average(sid, previous.id) if previous else None for sid in student_ids}
    change = {sid: round(average[sid] - before[sid], 1) if average[sid] is not None and before[sid] is not None
              else None for sid in student_ids}

    by_section = defaultdict(list)
    for sid in student_ids:
        by_section[system[sid]].append(sid)
    overall, overall_of, improved = {}, {}, {}
    subject_pos, subject_of = defaultdict(dict), defaultdict(dict)
    for section, ids in by_section.items():
        ranked = rankings.positions({sid: rankings.overall_score(section, raw[sid].values()) for sid in ids})
        overall.update(ranked)
        overall_of.update({sid: len(ranked) for sid in ranked})
        if section not in rankings.UNRANKED:
            improved.update(rankings.positions({sid: (change[sid],) if change[sid] is not None else None
                                                for sid in ids}))
        for subject in set().union(*(raw[sid].keys() for sid in ids)):
            ranked = rankings.positions({sid: rankings.subject_score(section, raw[sid].get(subject)) for sid in ids})
            for sid, place in ranked.items():
                subject_pos[sid][subject] = place
                subject_of[sid][subject] = len(ranked)

    rows = []
    for sid in student_ids:
        if sid not in visible_ids:
            continue
        s = data.students[sid]
        klass = s.school_class
        row = {
            "id": sid, "name": f"{s.first_name} {s.last_name}", "external_id": s.external_id,
            "class_name": klass.name if klass else None,
            "year_group_name": klass.year_group.name if klass else None,
            "section": SHORT_NAMES.get(system[sid], system[sid]),
            "average": average[sid], "previous": before[sid], "change": change[sid],
            "position": overall.get(sid), "of": overall_of.get(sid),
            "improvement_position": improved.get(sid),
            "subjects": {subject: round(p, 1) for subject, p in raw[sid].items()},
            "subject_positions": subject_pos.get(sid, {}), "subject_of": subject_of.get(sid, {}),
        }
        if system[sid] == "844":
            row.update(rankings.kcse_totals(raw[sid].values()))
        rows.append(row)
    rows.sort(key=lambda r: (r["position"] is None, r["position"] or 0, r["average"] is None,
                             -(r["average"] or 0), r["name"]))
    return rows


def student_analytics(data, student, term):
    sid = student.id
    system, scale = student_section(student)
    klass = student.school_class
    classmates = data.in_class(klass.id) if klass else []
    year_mates = data.in_year(klass.year_group_id) if klass else []
    return {
        "scope": "student", "name": f"{student.first_name} {student.last_name}",
        "class_name": klass.name if klass else None,
        "terms": _terms(data), "term": term.id if term else None,
        "trend": [
            {"term": t.name, "student": data.student_average(sid, t.id),
             "class": data.group_average(classmates, t.id) if klass else None,
             "year_group": data.group_average(year_mates, t.id) if klass else None}
            for t in data.graded_terms
        ],
        "subjects": _subject_rows(
            {subj: data.student_subject(sid, term.id, subj) for subj in data.marks.get((sid, term.id), {})}
            if term else {},
            data.group_subjects(classmates, term.id) if term and klass else {},
            "student", "class",
        ),
        "grading": _grading(system, scale),
    }


def _grading(system, scale):
    """Which curriculum and scale a view's levels use, so the app labels them right."""
    return {"system": system, "scale": scale, "levels": levels(scale)}


def class_analytics(data, school_class, term, visible_ids):
    ids = data.in_class(school_class.id)
    system, scale = section_for(school_class.year_group, data.school)
    year_ids = data.in_year(school_class.year_group_id)
    everyone = data.everyone()
    return {
        "scope": "class", "name": school_class.name, "year_group_name": school_class.year_group.name,
        "students_count": len(ids), "terms": _terms(data), "term": term.id if term else None,
        "trend": [
            {"term": t.name, "class": data.group_average(ids, t.id),
             "year_group": data.group_average(year_ids, t.id), "school": data.group_average(everyone, t.id)}
            for t in data.graded_terms
        ],
        "subjects": _subject_rows(data.group_subjects(ids, term.id) if term else {},
                                  data.group_subjects(year_ids, term.id) if term else {},
                                  "class", "year_group"),
        "distribution": data.distribution(ids, term.id, scale) if term else [],
        "students": _student_rows(data, ids, term, visible_ids),
        "grading": _grading(system, scale),
    }


def year_group_analytics(data, year_group, term, visible_ids):
    classes = list(SchoolClass.objects.filter(year_group=year_group).order_by("name"))
    ids = data.in_year(year_group.id)
    system, scale = section_for(year_group, data.school)
    everyone = data.everyone()
    return {
        "scope": "year_group", "name": year_group.name, "students_count": len(ids),
        "terms": _terms(data), "term": term.id if term else None,
        "series": [{"key": f"class_{c.id}", "label": c.name} for c in classes],
        "trend": [
            {"term": t.name, "year_group": data.group_average(ids, t.id), "school": data.group_average(everyone, t.id),
             **{f"class_{c.id}": data.group_average(data.in_class(c.id), t.id) for c in classes}}
            for t in data.graded_terms
        ],
        "groups": [
            {"id": c.id, "name": c.name, "students": len(data.in_class(c.id)),
             "average": data.group_average(data.in_class(c.id), term.id) if term else None}
            for c in classes
        ],
        "subjects": _subject_rows(data.group_subjects(ids, term.id) if term else {},
                                  data.group_subjects(everyone, term.id) if term else {},
                                  "year_group", "school"),
        "distribution": data.distribution(ids, term.id, scale) if term else [],
        "students": _student_rows(data, ids, term, visible_ids),
        "grading": _grading(system, scale),
    }


def school_analytics(data, school, term):
    years = list(YearGroup.objects.filter(school=school).order_by("name"))
    everyone = data.everyone()
    return {
        "scope": "school", "name": school.name, "students_count": len(everyone),
        "terms": _terms(data), "term": term.id if term else None,
        "series": [{"key": f"year_{y.id}", "label": y.name} for y in years],
        "trend": [
            {"term": t.name, "school": data.group_average(everyone, t.id),
             **{f"year_{y.id}": data.group_average(data.in_year(y.id), t.id) for y in years}}
            for t in data.graded_terms
        ],
        "groups": [
            {"id": y.id, "name": y.name, "students": len(data.in_year(y.id)),
             "average": data.group_average(data.in_year(y.id), term.id) if term else None}
            for y in years
        ],
        "subjects": _subject_rows(data.group_subjects(everyone, term.id) if term else {}, {}, "school", "unused"),
        "distribution": data.distribution(everyone, term.id) if term else [],
        # Admins only (the view checks): every student, ranked within their curriculum.
        "students": _student_rows(data, everyone, term, set(everyone)),
        "grading": _grading(school.education_system, school.grading_scale),
        # A school running two curricula gets a level spread for each, on its own scale.
        "distributions": _section_distributions(data, school, everyone, term),
    }


def _section_distributions(data, school, everyone, term):
    sections = school_sections(school)
    if len(sections) < 2 or term is None:
        return []
    return [{**section, "levels": levels(section["scale"]),
             "distribution": data.distribution([s for s in everyone if data.section_of(s)[0] == section["system"]],
                                               term.id, section["scale"])}
            for section in sections]
