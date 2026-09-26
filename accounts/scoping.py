"""
Who can see and change which students' data.

Admins can see and change everything at their school. Teachers only see
students in the classes they're assigned to (accounts.TeachingAssignment),
and only add or change grades for the subjects they teach in that class.
Every view that exposes student data goes through these helpers so the
rule lives in one place.
"""
from rest_framework.exceptions import PermissionDenied

from students.models import Student

from .models import TeachingAssignment


def is_admin(user):
    profile = getattr(user, "profile", None)
    return profile is not None and profile.is_admin


def assigned_class_ids(user):
    return TeachingAssignment.objects.filter(teacher=user.profile).values_list("school_class_id", flat=True)


def visible_students(user):
    """The students this staff member may see: all for admins, own classes for teachers."""
    students = Student.objects.filter(school=user.profile.school)
    if is_admin(user):
        return students
    return students.filter(school_class_id__in=assigned_class_ids(user))


def limit_to_visible_students(queryset, user, student_path="student"):
    """Narrow a queryset of student-linked rows (grades, attendance, reports) to visible students."""
    if is_admin(user):
        return queryset
    return queryset.filter(**{f"{student_path}__school_class_id__in": assigned_class_ids(user)})


def check_can_see_student(user, student):
    if is_admin(user):
        return
    if student.school_class_id is None or not TeachingAssignment.objects.filter(
        teacher=user.profile, school_class_id=student.school_class_id
    ).exists():
        raise PermissionDenied("You don't teach this student's class.")


def check_can_use_class(user, school_class):
    """For putting a student into a class: teachers may only use classes they teach."""
    if is_admin(user):
        return
    if school_class is None or not TeachingAssignment.objects.filter(
        teacher=user.profile, school_class=school_class
    ).exists():
        raise PermissionDenied("You can only put students in a class you teach.")


def check_can_grade(user, student, subject):
    if is_admin(user):
        return
    if student.school_class_id is None or not TeachingAssignment.objects.filter(
        teacher=user.profile, school_class_id=student.school_class_id, subject=subject
    ).exists():
        raise PermissionDenied(f"You don't teach {subject.name} to this student's class.")
