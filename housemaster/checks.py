"""
Deploy checks for configuration that can't stop the app from starting but
would quietly break it in production. They run with
`manage.py check --deploy` (CI runs it with --fail-level ERROR).
"""
from django.conf import settings
from django.core.checks import Error, Tags, register

CONSOLE_EMAIL = "django.core.mail.backends.console.EmailBackend"


@register(Tags.security, deploy=True)
def production_configuration(app_configs, **kwargs):
    if settings.DEBUG:
        return []
    messages = []
    frontend = settings.FRONTEND_URL or ""
    if not frontend.startswith("https://") or "localhost" in frontend or "127.0.0.1" in frontend:
        messages.append(Error(
            "FRONTEND_URL is not the deployed https frontend address.",
            hint="Invite and password-reset emails would link to a page nobody can open. "
                 "Set FRONTEND_URL to the Vercel production URL.",
            id="housemaster.E001",
        ))
    if settings.EMAIL_BACKEND == CONSOLE_EMAIL:
        messages.append(Error(
            "Email is going to the console backend.",
            hint="Invites and password resets would be written to the server log instead of being sent. "
                 "Set EMAIL_BACKEND, EMAIL_HOST and the related settings.",
            id="housemaster.E002",
        ))
    return messages
