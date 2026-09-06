from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

UserModel = get_user_model()


class EmailBackend(ModelBackend):
    """
    Authenticates by email + password instead of username + password.
    Email is now the identifier staff actually use — the `username` column
    still exists (Django's User model requires it) but is auto-derived and
    never surfaced, so this is what makes login, invites, and password
    resets all agree on the same identifier.

    Only kicks in when an `email` credential is supplied — e.g. the
    Django admin login form still submits `username`, so this backend
    no-ops for that and Django falls through to ModelBackend (also listed
    in AUTHENTICATION_BACKENDS), leaving /admin/ login unaffected.
    """

    def authenticate(self, request, email=None, password=None, **kwargs):
        if not email or not password:
            return None
        try:
            user = UserModel.objects.get(email__iexact=email)
        except UserModel.DoesNotExist:
            # Hash a password anyway so a nonexistent-email response takes
            # about as long as a wrong-password one (mirrors ModelBackend).
            UserModel().set_password(password)
            return None
        except UserModel.MultipleObjectsReturned:
            # Email isn't enforced unique at the DB level. If more than one
            # account shares it, refuse rather than guessing which was
            # meant — this needs cleaning up in the admin, not a silent pick.
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
