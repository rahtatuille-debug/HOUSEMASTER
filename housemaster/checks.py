"""
Deploy checks for configuration that can't stop the app from starting but
would quietly break it in production. They run with
`manage.py check --deploy` (CI runs it with --fail-level ERROR).
"""
from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

UNSENT_EMAIL_BACKENDS = {
    "django.core.mail.backends.console.EmailBackend",
    "housemaster.mail.UndeliveredEmailBackend",
}


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
    if settings.EMAIL_BACKEND in UNSENT_EMAIL_BACKENDS:
        messages.append(Error(
            "No email service is configured.",
            hint="Invites and password resets are not being delivered. "
                 "Set EMAIL_BACKEND, EMAIL_HOST and the related settings.",
            id="housemaster.E002",
        ))
    if settings.DRF_NUM_PROXIES is None:
        messages.append(Warning(
            "DRF_NUM_PROXIES is not set.",
            hint="The rate limits trust the whole X-Forwarded-For header, so a client can pick its own "
                 "IP address. Set DRF_NUM_PROXIES (docs/ENVIRONMENT.md explains how to find the value).",
            id="housemaster.W001",
        ))
    return messages
