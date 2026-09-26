"""Who receives an urgent alert."""
from django.contrib.auth.models import User
from django.db.models import Q

from .models import UrgentAlert


def alert_recipient_users(alert):
    """Active staff and/or parents at the alert's school matching its audience, minus the sender."""
    school = alert.school
    staff = Q(profile__school=school)
    parents = Q(guardian__school=school)
    audience = alert.audience
    if audience == UrgentAlert.Audience.EVERYONE:
        match = staff | parents
    elif audience == UrgentAlert.Audience.ALL_STAFF:
        match = staff
    elif audience == UrgentAlert.Audience.ALL_PARENTS:
        match = parents
    elif audience == UrgentAlert.Audience.YEAR_GROUP:
        match = parents & Q(
            guardian__students__school_class__year_group=alert.year_group, guardian__students__is_active=True
        )
    else:
        match = parents & Q(
            guardian__students__school_class=alert.school_class, guardian__students__is_active=True
        )
    users = User.objects.filter(match, is_active=True)
    if alert.created_by_id:
        users = users.exclude(id=alert.created_by_id)
    return users.distinct()
