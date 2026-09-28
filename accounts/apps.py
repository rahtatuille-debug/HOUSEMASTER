from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        # Registers the project's deploy checks (housemaster/checks.py).
        from housemaster import checks  # noqa: F401
