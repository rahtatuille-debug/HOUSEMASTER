"""
Joining a school with a login you already have (accounts/memberships.py). An invite, a staff sign-up or a new
school registration for an email that already signs in to HouseMaster adds that school to the same login: the
person proves it's theirs with their current password instead of choosing a new one.
"""
from django.contrib.auth import get_user_model
from rest_framework import serializers

WRONG_PASSWORD = ("That isn't the password for your HouseMaster account. Use the password you already sign in with "
                  "(or reset it from the sign-in page).")


def existing_login(email):
    """The login that signs in with this email, or None. Student accounts have no email."""
    return get_user_model().objects.filter(email__iexact=email).first()


def check_password(user, password, field="password"):
    if not user.check_password(password or ""):
        raise serializers.ValidationError({field: [WRONG_PASSWORD]})


def check_new_password(password, field="password"):
    """Django's password rules, reported against the form field."""
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    try:
        validate_password(password)
    except ValidationError as exc:
        raise serializers.ValidationError({field: list(exc.messages)})


def reopen(user):
    """Joining somewhere new reopens a login that every other school had closed."""
    if not user.is_active:
        user.is_active = True
        user.save(update_fields=["is_active"])
