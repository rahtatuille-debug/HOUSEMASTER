"""
Checks run before a migration changes what existing rows may hold. They print counts and IDs only, never names.
"""
from django.db.models import Count


def duplicate_admission_numbers(student_model):
    """(school id, number of duplicated admission numbers, number of students involved) for each school that has
    the same non-blank admission number on more than one student."""
    groups = (student_model.objects.exclude(external_id="").values("school_id", "external_id")
              .annotate(n=Count("id")).filter(n__gt=1))
    by_school = {}
    for g in groups:
        numbers, students = by_school.get(g["school_id"], (0, 0))
        by_school[g["school_id"]] = (numbers + 1, students + g["n"])
    return sorted((school, numbers, students) for school, (numbers, students) in by_school.items())


def describe(found):
    return "; ".join(f"school {school}: {numbers} admission number(s) shared by {students} students"
                     for school, numbers, students in found)
