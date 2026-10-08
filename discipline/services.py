"""Telling parents about a shared discipline record (a short email; the details stay in HouseMaster)."""
from django.utils import timezone

from .models import DisciplineIncident


def notify_parents(incident):
    """Returns how many parents are emailed."""
    from guardians.models import Guardian
    from guardians.notifications import _footer, send_after_commit

    student = incident.student
    school = student.school
    parents = (Guardian.objects.filter(students=student, email_notifications=True, user__is_active=True)
               .exclude(user__email="").select_related("user"))
    messages = [(
        f"A behaviour note from {school.name} about {student.first_name}",
        f"Dear {g.name},\n\n{school.name} has shared a behaviour record about {student.first_name} "
        f"{student.last_name}. Sign in to HouseMaster to read it." + _footer(school),
        g.user.email,
    ) for g in parents]
    if not messages:
        return 0

    def done(sent, attempted):
        DisciplineIncident.objects.filter(pk=incident.pk).update(parents_notified_at=timezone.now())

    send_after_commit(messages, on_done=done)
    return len(messages)
