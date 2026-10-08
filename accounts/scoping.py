"""
Who can see and change which students' data.

Admins can see and change everything at their school. Teachers see the
students in the classes they're assigned to (accounts.TeachingAssignment),
and only add or change grades for the subjects they teach in that class.

Staff roles (accounts.StaffRole) widen that, by area:

- "records": the student list, profile details, parents' contacts and
  health notes.
- "pastoral": attendance, behaviour, support and messaging parents
  ("attendance" is the same, except the Secretary keeps every register).
- "academic": grades, reports, subject comments and performance.

  Leadership            everything, in every area
  Head of Year          their year group's classes, in every area
  Class Teacher         their class, in every area
  Head of Department    classes taking their subject: records and academic
                        (and may grade that subject)
  Nurse / Secretary /   every student's record; nothing more unless they
  Admissions Officer    also teach

A governor sees no named student at all (school-wide figures only; the
gate is in accounts.authentication). Every view that exposes student data
goes through these helpers so the rules live in one place.
"""
from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from students.models import SchoolClass, Student

from .models import Profile, StaffRole, TeachingAssignment

RECORDS, PASTORAL, ACADEMIC = "records", "pastoral", "academic"
AREAS = (RECORDS, PASTORAL, ACADEMIC)
WHOLE_SCHOOL_RECORDS = {StaffRole.Role.NURSE, StaffRole.Role.SECRETARY, StaffRole.Role.ADMISSIONS}


def is_admin(user):
    profile = getattr(user, "profile", None)
    return profile is not None and profile.is_admin


def is_governor(user):
    profile = getattr(user, "profile", None)
    return profile is not None and profile.role == Profile.Role.GOVERNOR


def staff_roles(user):
    """This person's roles (cached on the user for the request)."""
    profile = getattr(user, "profile", None)
    if profile is None or profile.role == Profile.Role.GOVERNOR:
        return []
    cached = getattr(user, "_hm_staff_roles", None)
    if cached is None:
        cached = list(StaffRole.objects.filter(profile=profile))
        user._hm_staff_roles = cached
    return cached


def has_role(user, *roles):
    return any(r.role in roles for r in staff_roles(user))


def is_leader(user):
    """Admins and Leadership: whole-school pastoral and academic oversight (not settings or staff)."""
    return is_admin(user) or has_role(user, StaffRole.Role.LEADERSHIP)


def can_manage_admissions(user):
    return is_admin(user) or has_role(user, StaffRole.Role.ADMISSIONS)


def can_manage_parents(user):
    """Inviting and linking parents."""
    return is_admin(user) or has_role(user, StaffRole.Role.SECRETARY)


def can_send_announcements(user):
    """Announcements to the whole school (teachers can still post to their own classes)."""
    return is_leader(user) or has_role(user, StaffRole.Role.SECRETARY)


def is_nurse(user):
    return has_role(user, StaffRole.Role.NURSE)


def head_of_year_ids(user):
    return {r.year_group_id for r in staff_roles(user) if r.role == StaffRole.Role.HEAD_OF_YEAR}


def department_subject_ids(user):
    return {r.subject_id for r in staff_roles(user) if r.role == StaffRole.Role.HEAD_OF_DEPARTMENT}


def assigned_class_ids(user):
    """The classes this person teaches (their own timetable), whatever their roles."""
    return TeachingAssignment.objects.filter(teacher=user.profile).values_list("school_class_id", flat=True)


def scope_class_ids(user, area=PASTORAL):
    """
    The classes whose students this person may see in `area`: None means the
    whole school (including students not in a class); otherwise a set of ids.
    """
    if is_admin(user) or (not is_governor(user) and has_role(user, StaffRole.Role.LEADERSHIP)):
        return None
    if is_governor(user) or getattr(user, "profile", None) is None:
        return set()
    area = _area_scope(user, area)
    if area is None:
        return None
    if area == RECORDS and any(r.role in WHOLE_SCHOOL_RECORDS for r in staff_roles(user)):
        return None
    ids = set(assigned_class_ids(user))
    for r in staff_roles(user):
        if r.role == StaffRole.Role.CLASS_TEACHER:
            ids.add(r.school_class_id)
    years = head_of_year_ids(user)
    if years:
        ids |= set(SchoolClass.objects.filter(year_group_id__in=years).values_list("id", flat=True))
    subjects = department_subject_ids(user)
    if subjects and area in (RECORDS, ACADEMIC):
        ids |= set(TeachingAssignment.objects.filter(subject_id__in=subjects)
                   .values_list("school_class_id", flat=True))
    return ids


ATTENDANCE = "attendance"


def _area_scope(user, area):
    """Attendance is pastoral, except the Secretary keeps every register (late arrivals at the office)."""
    if area == ATTENDANCE:
        if has_role(user, StaffRole.Role.SECRETARY) and not is_governor(user):
            return None
        area = PASTORAL
    return area


def can_use_class(user, school_class_id, area=PASTORAL):
    scope = scope_class_ids(user, area)
    return scope is None or school_class_id in scope


def visible_students(user, area=PASTORAL):
    """The students this staff member may see in `area` (see the module docstring)."""
    students = Student.objects.filter(school=user.profile.school)
    scope = scope_class_ids(user, area)
    if scope is None:
        return students
    return students.filter(school_class_id__in=scope)


def limit_to_visible_students(queryset, user, student_path="student", area=PASTORAL):
    """Narrow a queryset of student-linked rows (grades, attendance, reports) to visible students."""
    scope = scope_class_ids(user, area)
    if scope is None:
        return queryset
    return queryset.filter(**{f"{student_path}__school_class_id__in": scope})


def check_can_see_student(user, student, area=PASTORAL):
    scope = scope_class_ids(user, area)
    if scope is None:
        return
    if student.school_class_id is None or student.school_class_id not in scope:
        raise PermissionDenied("You don't teach this student's class.")


def check_can_use_class(user, school_class):
    """For putting a student into a class: teachers may only use classes they teach (or lead)."""
    scope = scope_class_ids(user, PASTORAL)
    if scope is None:
        return
    if school_class is None or school_class.id not in scope:
        raise PermissionDenied("You can only put students in a class you teach.")


def check_can_grade(user, student, subject):
    if is_leader(user):
        return
    # A Head of Department may grade their subject in any class.
    if subject is not None and subject.id in department_subject_ids(user):
        return
    # An assignment with no subject covers every subject in that class.
    if student.school_class_id is None or not TeachingAssignment.objects.filter(
        Q(subject=subject) | Q(subject__isnull=True),
        teacher=user.profile, school_class_id=student.school_class_id,
    ).exists():
        raise PermissionDenied(f"You don't teach {subject.name} to this student's class.")


def can_approve_report(user, report):
    """Leadership approves any report; a Head of Year approves their own year group's."""
    if is_leader(user):
        return True
    klass = report.school_class or report.student.school_class
    return klass is not None and klass.year_group_id in head_of_year_ids(user)


def permissions_for(user):
    """What the app should offer this person (the server checks every request again)."""
    governor = is_governor(user)
    admin = is_admin(user)
    leader = is_leader(user) and not governor
    return {
        "is_admin": admin,
        "is_leader": leader,
        "is_governor": governor,
        "sees_whole_school": scope_class_ids(user, RECORDS) is None,
        "approve_reports": leader or bool(head_of_year_ids(user)),
        "approve_requests": leader,
        "manage_admissions": can_manage_admissions(user),
        "manage_parents": can_manage_parents(user),
        "manage_student_accounts": leader or can_manage_parents(user),
        "send_announcements": can_send_announcements(user),
        "send_alerts": leader,
        "nurse": is_nurse(user),
        "all_registers": scope_class_ids(user, ATTENDANCE) is None,
        "school_dashboard": leader,
        "manage_cover": leader,
        # The classes this person may work with in each area: null for the whole school.
        "classes": {area: (None if scope is None else sorted(scope))
                    for area in (*AREAS, ATTENDANCE) for scope in [scope_class_ids(user, area)]},
    }
