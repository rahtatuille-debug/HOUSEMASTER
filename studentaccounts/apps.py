from django.apps import AppConfig


class StudentAccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "studentaccounts"
    verbose_name = "Student accounts"

    def ready(self):
        from . import signals  # noqa: F401
