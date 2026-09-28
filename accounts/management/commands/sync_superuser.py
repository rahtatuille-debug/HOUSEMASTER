import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """
    Creates a superuser from the DJANGO_SUPERUSER_USERNAME/EMAIL/PASSWORD
    env vars if one doesn't exist yet. Safe to run on every deploy (the
    free tier has no shell): an existing superuser is left alone, so a
    password changed in the admin stays changed and the env var isn't a
    standing way in.

    To recover a lost password on a host with no shell, set
    SYNC_SUPERUSER_RESET_PASSWORD=true for one deploy: the password is then
    reset to DJANGO_SUPERUSER_PASSWORD, with a loud line in the deploy log.
    Remove the setting (and ideally the password variable) straight after.

    No-ops quietly if the username/password env vars aren't set.
    """

    help = "Create a superuser from DJANGO_SUPERUSER_* env vars if missing (reset only when asked)."

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")
        reset = os.environ.get("SYNC_SUPERUSER_RESET_PASSWORD", "").strip().lower() == "true"

        if not username or not password:
            self.stdout.write(
                "DJANGO_SUPERUSER_USERNAME/PASSWORD not set, skipping superuser sync."
            )
            return

        user = User.objects.filter(username=username).first()
        if user is None:
            User.objects.create_superuser(username=username, email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f"Created superuser {username!r}."))
        elif reset:
            user.set_password(password)
            user.is_staff = True
            user.is_superuser = True
            user.save()
            self.stdout.write(self.style.WARNING(
                f"!!! SUPERUSER PASSWORD RESET for {username!r} from DJANGO_SUPERUSER_PASSWORD "
                "(SYNC_SUPERUSER_RESET_PASSWORD=true). Every session of this account has ended. "
                "Now remove SYNC_SUPERUSER_RESET_PASSWORD from the environment. !!!"
            ))
        else:
            self.stdout.write(
                f"Superuser {username!r} already exists; its password was left unchanged. "
                "Set SYNC_SUPERUSER_RESET_PASSWORD=true for one deploy to reset it."
            )

        if not email:
            self.stdout.write(
                self.style.WARNING(
                    "DJANGO_SUPERUSER_EMAIL isn't set — this superuser can still use "
                    "the admin (username-based login), but can't log into the app itself, "
                    "since that now authenticates by email."
                )
            )
