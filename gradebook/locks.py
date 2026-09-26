"""
Locked terms. Once an admin locks a finished term, nothing that belongs to
it can change, for admins as well as teachers, until it's unlocked:
grades and reports for that term, and attendance on any date inside it.
"""
from rest_framework.exceptions import ValidationError

from .models import Term


def check_term_open(term):
    if term is not None and term.is_locked:
        raise ValidationError(f'{term.name} is locked. An admin must unlock it before anything in it can change.')


def locked_term_for_date(school, day):
    return Term.objects.filter(
        school=school, is_locked=True, start_date__lte=day, end_date__gte=day
    ).first()


def check_date_open(school, day):
    term = locked_term_for_date(school, day)
    if term is not None:
        raise ValidationError(
            f"{day} is in {term.name}, which is locked. An admin must unlock it before attendance can change."
        )
