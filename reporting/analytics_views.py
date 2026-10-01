from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import HasSchoolProfile
from accounts.scoping import is_admin, visible_students
from students.models import SchoolClass, YearGroup

from . import analytics


@api_view(["GET"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def performance(request):
    """
    ?scope=student|class|year_group|school&id=<id>&term=<term id, optional>

    Who can see what:
    - student: anyone who can see that student (admins, or their teachers);
    - class: admins, or teachers of that class;
    - year group: admins, or teachers of a class in it. Named students are
      limited to the ones the teacher can see; group figures are averages;
    - school: admins.
    """
    user = request.user
    school = user.profile.school
    scope = request.query_params.get("scope")
    object_id = request.query_params.get("id")
    # Refuse before loading every mark: that is the slow part for a school with years of history.
    if scope not in ("student", "class", "year_group", "school"):
        raise ValidationError("scope must be student, class, year_group or school.")
    if scope == "school" and not is_admin(user):
        raise PermissionDenied("Only admins can see the whole school.")
    data = analytics.SchoolGrades(school)
    term = data.term(request.query_params.get("term"))
    visible_ids = set(visible_students(user).values_list("id", flat=True))

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
        if not is_admin(user) and not user.profile.assignments.filter(school_class=school_class).exists():
            raise PermissionDenied("You can only see classes you teach.")
        return Response(analytics.class_analytics(data, school_class, term, visible_ids))

    if scope == "year_group":
        try:
            year_group = YearGroup.objects.get(pk=object_id, school=school)
        except (YearGroup.DoesNotExist, ValueError, TypeError):
            raise NotFound("Year group not found.")
        if not is_admin(user) and not user.profile.assignments.filter(
                school_class__year_group=year_group).exists():
            raise PermissionDenied("You can only see year groups you teach in.")
        return Response(analytics.year_group_analytics(data, year_group, term, visible_ids))

    if scope == "school":
        if not is_admin(user):
            raise PermissionDenied("Only admins can see the whole school.")
        return Response(analytics.school_analytics(data, school, term))

    raise ValidationError("scope must be student, class, year_group or school.")
