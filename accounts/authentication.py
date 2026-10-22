from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken

from .tokens import token_is_current

# A governor account is read-only and sees school-wide figures only, never a
# named student, so it may reach these and nothing else.
GOVERNOR_PATHS = ("/api/me/", "/api/governor/", "/api/logout/", "/api/tour-seen/")
# A student account sees only what's about that student (studentaccounts):
# their own record through the parents' child view, the calendar, and the
# student API. Until they choose their own password, only that.
# A school whose subscription has lapsed (billing): its admins may still see their account and pay; nobody
# else at the school gets in until the payment is recorded.
LOCKED_ADMIN_PATHS = ("/api/billing/",)
# While a school is locked for an unpaid subscription, staff keep what keeps children safe (BILL-001): registers,
# boarding and the sick bay, absences, messages to families and urgent alerts. Marks, reports, fees and the rest wait.
LOCKED_SAFEGUARDING_PATHS = ("/api/me/", "/api/logout/", "/api/attendance/", "/api/boarding/", "/api/absences/",
                             "/api/absence-reports/", "/api/conversations/", "/api/alerts/", "/api/push/")
# ...and can look up who is who for those pages, without changing anything.
LOCKED_READ_PATHS = ("/api/students/", "/api/school-classes/", "/api/year-groups/", "/api/staff/", "/api/terms/")
STUDENT_PATHS = ("/api/student/", "/api/guardian-students/", "/api/calendar/", "/api/logout/")
STUDENT_FIRST_PATHS = ("/api/student/me/", "/api/student/password/", "/api/logout/")


class VersionedJWTAuthentication(JWTAuthentication):
    """simplejwt's JWT authentication, refusing tokens from before a password change or deactivation."""

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if not token_is_current(validated_token, user):
            raise InvalidToken("This session has ended. Please sign in again.")
        return user

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            profile = getattr(result[0], "profile", None)
            if profile is not None and profile.role == "governor" and not request.path.startswith(GOVERNOR_PATHS):
                raise PermissionDenied("Governor accounts can only see the school's summary.")
            if profile is None and getattr(result[0], "guardian", None) is None:
                self._student_gate(result[0], request.path)
            self._billing_gate(result[0], profile, request.path, request.method)
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
    def _billing_gate(user, profile, path, method="GET"):
        from django.utils import timezone

        from billing.services import is_locked

        if profile is None:
            return  # families never lose access: the school pays HouseMaster, not them (BILL-001)
        if not is_locked(profile.school_id, timezone.localdate()):
            return
        if profile.role == "admin" and path.startswith(LOCKED_ADMIN_PATHS):
            return
        if path.startswith(LOCKED_SAFEGUARDING_PATHS):
            return
        if method in ("GET", "HEAD", "OPTIONS") and path.startswith(LOCKED_READ_PATHS):
            return
        raise PermissionDenied({
            "detail": "This part of HouseMaster is paused for your school because the subscription hasn't been paid. "
                      "Registers, boarding, the sick bay, absences, messages and alerts still work. Please contact "
                      "your school's administrator.",
            "code": "school_locked",
        })
