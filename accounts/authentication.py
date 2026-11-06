from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken

from .tokens import token_is_current

# A governor account is read-only and sees school-wide figures only, never a
# named student, so it may reach these and nothing else.
GOVERNOR_PATHS = ("/api/me/", "/api/governor/", "/api/logout/", "/api/tour-seen/", "/api/account/")
# A student account sees only what's about that student (studentaccounts):
# their own record through the parents' child view, the calendar, and the
# student API. Until they choose their own password, only that.
# A school whose subscription has lapsed (billing): its admins may still see their account and pay; nobody
# else at the school gets in until the payment is recorded.
LOCKED_ADMIN_PATHS = ("/api/me/", "/api/billing/", "/api/logout/")
# A school still being set up is open to its admins only. Other staff can see their account (the app tells them to
# wait); parents and students can only sign out until the admin opens the school.
SETUP_STAFF_PATHS = ("/api/me/", "/api/logout/", "/api/tour-seen/")
SETUP_FAMILY_PATHS = ("/api/logout/",)
# Someone at several schools can always see their schools and move to another, whatever this one's state.
ACCOUNT_PATHS = ("/api/account/",)
STUDENT_PATHS = ("/api/student/", "/api/guardian-students/", "/api/calendar/", "/api/logout/")
STUDENT_FIRST_PATHS = ("/api/student/me/", "/api/student/password/", "/api/logout/")


class VersionedJWTAuthentication(JWTAuthentication):
    """simplejwt's JWT authentication, refusing tokens from before a password change or deactivation."""

    def get_user(self, validated_token):
        from .memberships import MEMBERSHIP_CLAIM, act_as, default_for, find

        user = super().get_user(validated_token)
        if not token_is_current(validated_token, user):
            raise InvalidToken("This session has ended. Please sign in again.")
        # The school this session acts as. Tokens from before one login could have several carry none: theirs is
        # the only one. A membership deactivated since (or not this user's) ends the session.
        key = validated_token.get(MEMBERSHIP_CLAIM)
        membership = find(user, key) if key else default_for(user)
        if key and membership is None:
            raise InvalidToken("You no longer have access to that school. Please sign in again.")
        act_as(user, membership)
        return user

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            profile = getattr(result[0], "profile", None)
            if profile is not None and profile.role == "governor" and not request.path.startswith(GOVERNOR_PATHS):
                raise PermissionDenied("Governor accounts can only see the school's summary.")
            if profile is None and getattr(result[0], "guardian", None) is None:
                self._student_gate(result[0], request.path)
            self._school_gates(result[0], profile, request.path)
        return result

    @staticmethod
    def _student_gate(user, path):
        from studentaccounts.services import account_of

        account = account_of(user)
        if account is None:
            return
        if not account.student.is_active:
            raise PermissionDenied("This student account is closed.")
        if account.must_change_password and not path.startswith(STUDENT_FIRST_PATHS):
            raise PermissionDenied({"detail": "Choose your own password first.", "code": "password_change_required"})
        if not path.startswith(STUDENT_PATHS) or path.startswith("/api/calendar/events/"):
            raise PermissionDenied("Student accounts can only see their own information.")

    @staticmethod
    def _school_gates(user, profile, path):
        """The school's subscription (billing) and whether its admin has finished setting it up."""
        from django.utils import timezone

        from billing.services import is_locked

        if profile is not None:
            school = profile.school
        elif getattr(user, "guardian", None) is not None:
            school = user.guardian.school
        else:
            from studentaccounts.services import account_of

            account = account_of(user)
            school = account.student.school if account else None
        if school is None or path.startswith(ACCOUNT_PATHS):
            return
        admin = profile is not None and profile.role == "admin"
        if is_locked(school.id, timezone.localdate()) and not (admin and path.startswith(LOCKED_ADMIN_PATHS)):
            raise PermissionDenied({
                "detail": "HouseMaster is paused for your school because the subscription hasn't been paid. "
                          "Please contact your school's administrator.",
                "code": "school_locked",
            })
        if admin or path.startswith(SETUP_STAFF_PATHS if profile is not None else SETUP_FAMILY_PATHS):
            return
        if school.setup_completed_at is None:
            raise PermissionDenied({
                "detail": "Your school is still being set up on HouseMaster. You'll be able to sign in as soon as "
                          "its administrator has finished.",
                "code": "school_not_open",
            })
