"""
The sample report card in the setup wizard: the real report card PDF, for a
made-up student, in the style the school has chosen so far (its name, system,
grading, subjects and report tone).

Everything is built inside a transaction that is always rolled back, so the
sample goes through exactly the same code as a real report card and nothing
is ever saved.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from attendance.models import AttendanceRecord
from gradebook.levels import level_for
from gradebook.models import Grade, StudentSubject, Subject, SubjectReport, Term
from gradebook.systems import REPORT_EXTRAS
from students.models import School, SchoolClass, Student, YearGroup
from students.presets import SYSTEMS, suggested_terms
from students.samples import PRINCIPAL_COMMENT, SAMPLE_STUDENT, SUBJECT_COMMENTS, TEACHER_COMMENTS, band, names

from .exports import reports_pdf
from .models import StudentReport

# The sample student's marks, subject by subject (repeated if there are more subjects).
SCORES = [81, 67, 74, 58, 88, 63, 71, 69, 77, 55]
# Classmates, so 8-4-4 positions have something to count.
CLASSMATE_SCORES = [72, 55, 90, 61, 48, 79, 66, 58]
MAX_SUBJECTS = 9
# American letter grades start higher, so a typical student there scores higher too.
LIFT = {"american": 12}
DEFAULT_COUNTRY = {"cbc": "ke", "844": "ke", "british": "gb", "american": "us"}


def _default_year_group(system):
    stages = SYSTEMS[system]["stages"]
    stage = stages[len(stages) // 2]
    return {"name": stage["year_groups"][len(stage["year_groups"]) // 2], "classes": []}, stage["subjects"]


def sample_report_pdf(settings):
    """
    settings: the wizard's answers so far: education_system (required), and
    optionally name, motto, address, phone, email, country, grading_scale,
    report_tone, year_groups [{name, classes}], subjects [names], terms
    [{name, start_date, end_date}] and vocab_overrides.
    Returns the PDF as bytes.
    """
    system = settings["education_system"]
    country = settings.get("country") or DEFAULT_COUNTRY.get(system, "other")
    tone = settings.get("report_tone") or "formal"
    scale = settings.get("grading_scale") or SYSTEMS[system]["scales"][0]
    default_group, default_subjects = _default_year_group(system)
    groups = [g for g in settings.get("year_groups") or [] if g.get("name")]
    group = groups[len(groups) // 2] if groups else default_group
    subject_names = list(dict.fromkeys(settings.get("subjects") or default_subjects))[:MAX_SUBJECTS]
    term_spec = (settings.get("terms") or suggested_terms(system))[0]

    with transaction.atomic():
        school = School.objects.create(
            name=settings.get("name") or "Your School", motto=settings.get("motto", ""),
            address=settings.get("address", ""), phone=settings.get("phone", ""), email=settings.get("email", ""),
            education_system=system, grading_scale=scale, country=country, report_tone=tone,
            vocab_overrides=settings.get("vocab_overrides") or {},
        )
        year_group = YearGroup.objects.create(school=school, name=group["name"])
        class_names = list(dict.fromkeys(group.get("classes") or [])) or [group["name"]]
        klass = SchoolClass.objects.create(year_group=year_group, name=class_names[0])
        other = SchoolClass.objects.create(year_group=year_group, name=class_names[1] if len(class_names) > 1
                                           else f"{class_names[0]} (another class)")
        start = date.fromisoformat(str(term_spec["start_date"]))
        end = date.fromisoformat(str(term_spec["end_date"]))
        term = Term.objects.create(school=school, name=term_spec["name"], start_date=start, end_date=end)
        subjects = [Subject.objects.create(school=school, name=n) for n in subject_names]

        first, last = SAMPLE_STUDENT.get(country, SAMPLE_STUDENT["other"])
        student = Student.objects.create(school=school, school_class=klass, first_name=first, last_name=last,
                                         external_id="SAMPLE-001")
        girls, boys, surnames = names(country)
        for i, base in enumerate(CLASSMATE_SCORES):
            mate = Student.objects.create(school=school, school_class=klass if i % 2 else other,
                                          first_name=(girls + boys)[i], last_name=surnames[i])
            Grade.objects.bulk_create([Grade(student=mate, subject=s, term=term,
                                             score=Decimal(min(100, base + j % 5 + LIFT.get(system, 0))),
                                             max_score=Decimal(100)) for j, s in enumerate(subjects)])

        dp = system == "ib" and group["name"].upper().startswith("DP")
        grades, entries = [], []
        for i, subject in enumerate(subjects):
            score = min(100, SCORES[i % len(SCORES)] + LIFT.get(system, 0))
            grades.append(Grade(student=student, subject=subject, term=term, score=Decimal(score),
                                max_score=Decimal(100)))
            entry = SubjectReport(student=student, subject=subject, term=term,
                                  comment=SUBJECT_COMMENTS[band(score)][i % 4])
            if system == "british":
                entry.effort = str(1 + i % 3)
                entry.target = level_for(min(100, score + 8), scale) or ""
            elif system == "ib" and not dp:
                entry.criteria = {c: max(0, min(8, round(score / 100 * 8) + (k % 3) - 1)) for k, c in enumerate("ABCD")}
            entries.append(entry)
            if dp:
                StudentSubject.objects.create(student=student, subject=subject, level="HL" if i < 3 else "SL")
        Grade.objects.bulk_create(grades)
        SubjectReport.objects.bulk_create(entries)

        # About twelve weeks of attendance: a couple of absences and a late morning.
        days = [start + timedelta(days=d) for d in range(0, 90) if (start + timedelta(days=d)).weekday() < 5
                and start + timedelta(days=d) <= end]
        AttendanceRecord.objects.bulk_create([
            AttendanceRecord(student=student, date=day, status="absent" if i in (9, 31) else "late" if i == 20
                             else "present") for i, day in enumerate(days)])

        ranked = sorted(zip(subject_names, SCORES * 2), key=lambda x: x[1])
        extra = {g["key"]: {item: g["ratings"][k % 2] for k, item in enumerate(g["items"])}
                 for g in REPORT_EXTRAS.get(system, [])}
        from students.presets import school_vocab

        words = school_vocab(school)
        report = StudentReport(
            student=student, term=term, status="finalized", finalized_at=timezone.now(), extra=extra,
            progress_summary="Sample", principal_comment=PRINCIPAL_COMMENT.format(term=words["term"].lower()),
            report_comment=TEACHER_COMMENTS.get(tone, TEACHER_COMMENTS["formal"]).format(
                name=first, best=ranked[-1][0] if ranked else "class", weakest=ranked[0][0] if ranked else "class",
                subjects=words["subjects"].lower(), term=words["term"].lower()),
        )
        report.record_class()  # as finalizing would
        report.save()
        pdf, _count = reports_pdf(school, [student], term)
        transaction.set_rollback(True)
    return pdf
