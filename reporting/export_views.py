from datetime import date, timedelta

from django.http import HttpResponse
from django.utils.text import slugify
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from accounts.permissions import HasSchoolProfile
from accounts.scoping import ACADEMIC, ATTENDANCE, RECORDS, can_use_class, visible_students
from activity.services import log_activity
from gradebook.models import Term
from students.models import SchoolClass
from students.presets import section_for

from . import exports

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _class(request, area):
    """The requested class, if it's at the requester's school and they may see it for this export."""
    try:
        school_class = SchoolClass.objects.select_related("year_group").get(
            pk=request.query_params.get("school_class"), year_group__school=request.user.profile.school
        )
    except (SchoolClass.DoesNotExist, ValueError, TypeError):
        raise NotFound("Class not found.")
    if not can_use_class(request.user, school_class.id, area):
        raise PermissionDenied("You can only export classes you teach.")
    request._export_area = area
    return school_class


def _words(request):
    from students.presets import school_vocab
    return school_vocab(request.user.profile.school)


def _term(request):
    try:
        return Term.objects.get(pk=request.query_params.get("term"), school=request.user.profile.school)
    except (Term.DoesNotExist, ValueError, TypeError):
        raise NotFound("Term not found.")


def _students(request, school_class):
    return (visible_students(request.user, request._export_area).filter(school_class=school_class, is_active=True)
            .select_related("school_class__year_group").prefetch_related("guardians__user")
            .order_by("last_name", "first_name"))


def _file(content, content_type, filename, request, what):
    log_activity(school=request.user.profile.school, actor=request.user, action="export.downloaded",
                 summary=f"Downloaded {what}")
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@api_view(["GET"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def export_class_list(request):
    school_class = _class(request, RECORDS)
    content = exports.class_list_xlsx(_students(request, school_class), words=_words(request))
    return _file(content, XLSX, f"class-list-{slugify(school_class.name)}.xlsx", request,
                 f"the class list for {school_class.name}")


@api_view(["GET"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def export_grades(request):
    school_class, term = _class(request, ACADEMIC), _term(request)
    # The class's own curriculum and grading (a school can run two).
    system, scale = section_for(school_class.year_group, request.user.profile.school)
    content = exports.grades_xlsx(_students(request, school_class), term, scale=scale, words=_words(request),
                                  system=system)
    return _file(content, XLSX, f"grades-{slugify(school_class.name)}-{slugify(term.name)}.xlsx", request,
                 f"{term.name} grades for {school_class.name}")


@api_view(["GET"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def export_attendance(request):
    school_class = _class(request, ATTENDANCE)
    try:
        start = date.fromisoformat(request.query_params.get("start", ""))
        end = date.fromisoformat(request.query_params.get("end", ""))
    except ValueError:
        raise ValidationError("Give a start and end date (YYYY-MM-DD).")
    if end < start or end - start > timedelta(days=400):
        raise ValidationError("The end date must be after the start, and at most about a year later.")
    content = exports.attendance_xlsx(_students(request, school_class), start, end, words=_words(request))
    return _file(content, XLSX, f"attendance-{slugify(school_class.name)}-{start}-to-{end}.xlsx", request,
                 f"attendance for {school_class.name}, {start} to {end}")


@api_view(["GET"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def export_reports(request):
    school_class, term = _class(request, ACADEMIC), _term(request)
    content, count = exports.reports_pdf(request.user.profile.school, _students(request, school_class), term)
    if count == 0:
        raise NotFound(f"No finalized {term.name} reports for {school_class.name} yet.")
    return _file(content, "application/pdf", f"reports-{slugify(school_class.name)}-{slugify(term.name)}.pdf",
                 request, f"{count} finalized {term.name} reports for {school_class.name}")
