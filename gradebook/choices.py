"""
Who takes which subject: every student takes the core subjects, and an
elective only if they chose it. IB students can take a subject at Higher or
Standard Level, and CBC senior school students follow a pathway.

The class grid here lets an admin or one of the class's teachers set the
choices for a whole class at once.
"""
from django.db import transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import HasSchoolProfile
from accounts.scoping import is_admin, visible_students
from activity.services import log_activity
from students.models import SchoolClass

from .models import StudentSubject, Subject

LEVELS = {"", "HL", "SL"}


def takes(student, subject):
    """Whether the student studies this subject."""
    return not subject.is_elective or StudentSubject.objects.filter(student=student, subject=subject).exists()


def check_takes(student, subject):
    if not takes(student, subject):
        raise ValidationError(f"{student.first_name} {student.last_name} doesn't take {subject.name}. "
                              "Add it to their subject choices first.")


def levels_for(student):
    """{subject_id: "HL" | "SL"} for subjects the student takes at a set level."""
    return dict(StudentSubject.objects.filter(student=student).exclude(level="").values_list("subject_id", "level"))


def _class(request, value):
    try:
        return SchoolClass.objects.select_related("year_group").get(
            pk=value, year_group__school=request.user.profile.school)
    except (SchoolClass.DoesNotExist, ValueError, TypeError):
        raise NotFound("Class not found.")


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def class_subject_choices(request):
    """
    GET ?school_class: the class's students with their electives, levels and
    pathway. POST {school_class, students: [{student, pathway, subjects:
    [{subject, level}]}]}: replace those students' choices. Admins and the
    class's teachers can do this.
    """
    from students.presets import PATHWAYS

    data = request.query_params if request.method == "GET" else request.data
    school_class = _class(request, data.get("school_class"))
    school = request.user.profile.school
    if not is_admin(request.user) and not request.user.profile.assignments.filter(school_class=school_class).exists():
        raise PermissionDenied("You can only set subject choices for a class you teach.")
    students = list(visible_students(request.user).filter(school_class=school_class, is_active=True)
                    .order_by("last_name", "first_name"))
    subjects = list(Subject.objects.filter(school=school).order_by("name"))
    pathways = PATHWAYS.get(school.education_system, [])

    if request.method == "POST":
        by_id = {s.id: s for s in students}
        subject_ids = {s.id for s in subjects}
        rows = data.get("students")
        if not isinstance(rows, list):
            raise ValidationError({"students": "Send a list of students."})
        with transaction.atomic():
            for row in rows:
                student = by_id.get(row.get("student") if isinstance(row, dict) else None)
                if student is None:
                    raise ValidationError({"students": "Every row must be a student in this class."})
                pathway = str(row.get("pathway", "") or "")
                if pathway and pathway not in pathways:
                    raise ValidationError({"students": f'"{pathway}" isn\'t a pathway here.'})
                choices = {}
                for item in row.get("subjects") or []:
                    subject_id, level = item.get("subject"), str(item.get("level", "") or "")
                    if subject_id not in subject_ids or level not in LEVELS:
                        raise ValidationError({"students": "Unknown subject or level."})
                    choices[subject_id] = level
                if student.pathway != pathway:
                    student.pathway = pathway
                    student.save(update_fields=["pathway"])
                StudentSubject.objects.filter(student=student).exclude(subject_id__in=choices).delete()
                for subject_id, level in choices.items():
                    StudentSubject.objects.update_or_create(student=student, subject_id=subject_id,
                                                            defaults={"level": level})
            log_activity(school=school, actor=request.user, action="subject_choices.saved", target=school_class,
                         summary=f"Updated subject choices for {len(rows)} students in {school_class.name}")

    chosen = {}
    for c in StudentSubject.objects.filter(student__in=students):
        chosen.setdefault(c.student_id, []).append({"subject": c.subject_id, "level": c.level})
    return Response({
        "subjects": [{"id": s.id, "name": s.name, "is_elective": s.is_elective} for s in subjects],
        "pathways": pathways,
        "students": [{"student": s.id, "name": f"{s.first_name} {s.last_name}", "pathway": s.pathway,
                      "subjects": chosen.get(s.id, [])} for s in students],
    })
