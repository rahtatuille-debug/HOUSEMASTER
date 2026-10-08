from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import HasSchoolProfile
from accounts.scoping import ACADEMIC, can_use_class, is_leader, scope_class_ids, visible_students
from students.models import SchoolClass, YearGroup

from . import analytics


@api_view(["GET"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def performance(request):
    """
    ?scope=student|class|year_group|school&id=<id>&term=<term id, optional>

    Who can see what:
    - student: anyone who can see that student's grades (accounts.scoping, "academic");
    - class: anyone whose academic scope covers the class;
    - year group: leaders, or anyone whose academic scope covers a class in it.
      Named students are limited to the ones they can see; group figures are averages;
    - school: admins and leadership.
    """
    user = request.user
    school = user.profile.school
    scope = request.query_params.get("scope")
    object_id = request.query_params.get("id")
    # Refuse before loading every mark: that is the slow part for a school with years of history.
    if scope not in ("student", "class", "year_group", "school"):
        raise ValidationError("scope must be student, class, year_group or school.")
    if scope == "school" and not is_leader(user):
        raise PermissionDenied("Only admins and leadership can see the whole school.")
    data = analytics.SchoolGrades(school)
    term = data.term(request.query_params.get("term"))
    visible_ids = set(visible_students(user, ACADEMIC).values_list("id", flat=True))

    if scope == "student":
        student = data.students.get(int(object_id)) if str(object_id).isdigit() else None
        if student is None or student.id not in visible_ids:
            raise NotFound("Student not found.")
        return Response(analytics.student_analytics(data, student, term))

    if scope == "class":
        try:
            school_class = SchoolClass.objects.select_related("year_group").get(
                pk=object_id, year_group__school=school)
        except (SchoolClass.DoesNotExist, ValueError, TypeError):
            raise NotFound("Class not found.")
        if not can_use_class(user, school_class.id, ACADEMIC):
            raise PermissionDenied("You can only see classes you teach.")
        return Response(analytics.class_analytics(data, school_class, term, visible_ids))

    if scope == "year_group":
        try:
            year_group = YearGroup.objects.get(pk=object_id, school=school)
        except (YearGroup.DoesNotExist, ValueError, TypeError):
            raise NotFound("Year group not found.")
        classes = scope_class_ids(user, ACADEMIC)
        if classes is not None and not year_group.classes.filter(id__in=classes).exists():
            raise PermissionDenied("You can only see year groups you teach in.")
        return Response(analytics.year_group_analytics(data, year_group, term, visible_ids))

    if scope == "school":
        if not is_leader(user):
            raise PermissionDenied("Only admins and leadership can see the whole school.")
        return Response(analytics.school_analytics(data, school, term))

    raise ValidationError("scope must be student, class, year_group or school.")
