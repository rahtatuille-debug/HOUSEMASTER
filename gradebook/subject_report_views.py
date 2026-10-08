"""
Per-subject end-of-term entries (comment, effort, target, MYP criteria) for a
class, entered on one screen by the subject's teacher, and a student's term
summary in their school's system.
"""
from django.db import transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import HasSchoolProfile
from accounts.scoping import ACADEMIC, can_use_class, check_can_grade, visible_students
from activity.services import log_activity
from students.models import SchoolClass

from .locks import check_term_open
from .models import Subject, SubjectReport, Term
from .systems import CRITERIA, SUBJECT_FIELDS

MAX_COMMENT = 2000


def _lookup(request, data):
    school = request.user.profile.school
    try:
        term = Term.objects.get(pk=data.get("term"), school=school)
        subject = Subject.objects.get(pk=data.get("subject"), school=school)
        school_class = SchoolClass.objects.get(pk=data.get("school_class"), year_group__school=school)
    except (Term.DoesNotExist, Subject.DoesNotExist, SchoolClass.DoesNotExist, ValueError, TypeError):
        raise NotFound("Term, subject or class not found.")
    from students.presets import section_for

    from .choices import subject_system

    if subject_system(subject, school) != section_for(school_class.year_group, school)[0]:
        raise ValidationError(f"{subject.name} isn't part of {school_class.name}'s curriculum.")
    return term, subject, school_class


def _row(student, entry):
    return {
        "student": student.id, "name": f"{student.first_name} {student.last_name}",
        "comment": entry.comment if entry else "", "effort": entry.effort if entry else "",
        "target": entry.target if entry else "", "criteria": entry.criteria if entry else {},
    }


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def class_subject_reports(request):
    """
    GET ?term&subject&school_class: every active student in the class with
    their entry. POST {term, subject, school_class, entries: [{student,
    comment, effort, target, criteria}]}: save the entries; teachers can only
    save for subjects they teach in that class.
    """
    data = request.query_params if request.method == "GET" else request.data
    term, subject, school_class = _lookup(request, data)
    if not can_use_class(request.user, school_class.id, ACADEMIC):
        raise PermissionDenied("You don't teach this class.")
    students = visible_students(request.user, ACADEMIC).filter(school_class=school_class, is_active=True)
    if subject.is_elective:
        students = students.filter(subject_choices__subject=subject)
    students = list(students.order_by("last_name", "first_name"))
    if request.method == "GET":
        entries = {e.student_id: e for e in SubjectReport.objects.filter(term=term, subject=subject, student__in=students)}
        from students.presets import section_for

        system, _scale = section_for(school_class.year_group, request.user.profile.school)
        return Response({"fields": SUBJECT_FIELDS.get(system, []),
                         "students": [_row(s, entries.get(s.id)) for s in students]})

    check_term_open(term)
    by_id = {s.id: s for s in students}
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise ValidationError({"entries": "Send a list of entries."})
    saved = 0
    with transaction.atomic():
        for item in entries:
            student = by_id.get(item.get("student") if isinstance(item, dict) else None)
            if student is None:
                raise ValidationError({"entries": "Every entry must be for a student in this class."})
            check_can_grade(request.user, student, subject)
            comment = str(item.get("comment", "")).strip()
            if len(comment) > MAX_COMMENT:
                raise ValidationError({"entries": f"Comments must be {MAX_COMMENT} characters or fewer."})
            criteria = item.get("criteria") or {}
            if not isinstance(criteria, dict) or any(
                    k not in CRITERIA or v not in (None, "") and not (str(v).isdigit() and 0 <= int(v) <= 8)
                    for k, v in criteria.items()):
                raise ValidationError({"entries": "MYP criteria are A to D, each 0 to 8."})
            values = {
                "comment": comment, "effort": str(item.get("effort", "")).strip()[:10],
                "target": str(item.get("target", "")).strip()[:10],
                "criteria": {k: int(v) for k, v in criteria.items() if v not in (None, "")},
            }
            SubjectReport.objects.update_or_create(student=student, subject=subject, term=term, defaults=values)
            saved += 1
        if saved:
            log_activity(
                school=term.school, actor=request.user, action="subject_report.saved", target=subject,
                summary=f"Saved {subject.name} report entries for {saved} students in {school_class.name}, {term.name}",
            )
    return Response({"saved": saved})
