from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        # Registers the project's deploy checks (housemaster/checks.py).
        from housemaster import checks  # noqa: F401

        # Ends a user's sessions when their password changes (accounts/tokens.py).
        from . import signals

        # One login, several schools: user.profile / user.guardian are the session's membership.
        from .memberships import install

        install()
        signals.connect_membership_signals()
