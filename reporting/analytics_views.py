from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import HasSchoolProfile
from accounts.scoping import ACADEMIC, can_use_class, is_leader, scope_class_ids, visible_students
from students.models import SchoolClass, YearGroup
from students.presets import section_for

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


@api_view(["GET"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def charts(request):
    """
    ?chart=subject_trends|assessment_types|marks|ranks&scope=student&id=<student>&term=<term, optional>
    &subject=<subject name, optional; assessment_types only>. subject_trends also takes scope=class|year_group|school,
    with the same rules as /api/analytics/performance/. Who may see a student, and the answer when they may not,
    are exactly those of the performance endpoint. See reporting/charts.py and docs/CHARTS.md.
    """
    from gradebook.models import Term
    from students.models import Student

    from . import charts as chart_data

    user = request.user
    school = user.profile.school
    chart = request.query_params.get("chart")
    scope = request.query_params.get("scope")
    object_id = request.query_params.get("id")
    if chart not in chart_data.CHARTS:
        raise ValidationError(f"chart must be one of {', '.join(chart_data.CHARTS)}.")
    if scope not in ("student", "class", "year_group", "school"):
        raise ValidationError("scope must be student, class, year_group or school.")
    if scope != "student" and chart != "subject_trends":
        raise ValidationError("Only subject_trends has class, year group and school scopes.")
    if scope == "school" and not is_leader(user):
        raise PermissionDenied("Only admins and leadership can see the whole school.")

    if scope == "student":
        visible = visible_students(user, ACADEMIC)
        if chart == "marks":
            # One student's marks: no need to load the whole school.
            student = visible.filter(pk=object_id, is_active=True).select_related("school", "school_class__year_group") \
                .first() if str(object_id).isdigit() else None
            if student is None:
                raise NotFound("Student not found.")
            term_id = request.query_params.get("term")
            terms = Term.objects.filter(school=school)
            term = terms.filter(pk=term_id).first() if str(term_id or "").isdigit() else \
                terms.filter(grades__student=student).order_by("-start_date", "-id").first()
            return Response(chart_data.marks_in_term(student, term))
        data = analytics.SchoolGrades(school)
        student = data.students.get(int(object_id)) if str(object_id).isdigit() else None
        if student is None or not visible.filter(pk=student.id).exists():
            raise NotFound("Student not found.")
        if chart == "subject_trends":
            return Response(chart_data.student_subject_trends(data, student))
        if chart == "assessment_types":
            term = data.term(request.query_params.get("term"))
            return Response(chart_data.student_assessment_types(data, student, term,
                                                                request.query_params.get("subject") or None))
        return Response(chart_data.student_ranks(data, student, with_school=is_leader(user)))

    # Group scopes (subject_trends only): the same checks, in the same order, as the performance endpoint.
    data = analytics.SchoolGrades(school)
    if scope == "class":
        try:
            school_class = SchoolClass.objects.select_related("year_group").get(pk=object_id, year_group__school=school)
        except (SchoolClass.DoesNotExist, ValueError, TypeError):
            raise NotFound("Class not found.")
        if not can_use_class(user, school_class.id, ACADEMIC):
            raise PermissionDenied("You can only see classes you teach.")
        system, scale = section_for(school_class.year_group, school)
        return Response(chart_data.group_subject_trends(data, scope, school_class.name, data.in_class(school_class.id),
                                                        analytics._grading(system, scale)))
    if scope == "year_group":
        try:
            year_group = YearGroup.objects.get(pk=object_id, school=school)
        except (YearGroup.DoesNotExist, ValueError, TypeError):
            raise NotFound("Year group not found.")
        classes = scope_class_ids(user, ACADEMIC)
        if classes is not None and not year_group.classes.filter(id__in=classes).exists():
            raise PermissionDenied("You can only see year groups you teach in.")
        system, scale = section_for(year_group, school)
        return Response(chart_data.group_subject_trends(data, scope, year_group.name, data.in_year(year_group.id),
                                                        analytics._grading(system, scale)))
    return Response(chart_data.group_subject_trends(data, scope, school.name, data.everyone(),
                                                    analytics._grading(school.education_system, school.grading_scale)))
