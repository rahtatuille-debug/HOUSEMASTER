from django.contrib.auth.models import User
from django.db.models import Count
from django.db.models.functions import Lower
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """
    Read-only report of accounts that would block (or be broken by) adding
    a unique constraint on User.email:

    - emails shared by more than one account, compared case-insensitively
      since that's how EmailBackend looks them up — any account in such a
      group currently can't log into the app at all;
    - accounts with no email, which can't log into the app either (only
      /admin/, by username).

    Changes nothing, so it's safe to add to the Render build command to see
    the result in the build log (the free tier has no shell). Run it before
    adding `unique=True` to User.email.
    """

    help = "Report duplicate (case-insensitive) and missing emails on User accounts."

    def handle(self, *args, **options):
        duplicates = (
            User.objects.exclude(email="")
            .annotate(email_lower=Lower("email"))
            .values("email_lower")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
            .order_by("email_lower")
        )

        if duplicates:
            self.stdout.write(
                self.style.WARNING(f"{len(duplicates)} email(s) shared by multiple accounts:")
            )
            for row in duplicates:
                users = User.objects.filter(email__iexact=row["email_lower"]).order_by("id")
                ids = ", ".join(f"id={u.pk} username={u.username!r}" for u in users)
                self.stdout.write(f"  {row['email_lower']}: {ids}")
        else:
            self.stdout.write(self.style.SUCCESS("No duplicate emails."))

        blank = User.objects.filter(email="").order_by("id")
        if blank:
            self.stdout.write(
                self.style.WARNING(f"{blank.count()} account(s) with no email (can't log into the app):")
            )
            for u in blank:
                self.stdout.write(f"  id={u.pk} username={u.username!r}")
        else:
            self.stdout.write(self.style.SUCCESS("No accounts without an email."))
