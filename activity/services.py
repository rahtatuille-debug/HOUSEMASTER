from .models import ActivityLog


def display_name(user):
    """A person's name as shown in the product, never their email."""
    if user is None:
        return "System"
    profile = getattr(user, "profile", None)
    if profile is not None:
        return profile.name
    guardian = getattr(user, "guardian", None)
    if guardian is not None:
        return guardian.name
    return user.get_full_name().strip() or "Unknown user"


def student_name(student):
    return f"{student.first_name} {student.last_name}".strip()


def log_activity(*, school, actor, action, summary, target=None, **details):
    """
    Record one entry in the school's activity log. `target` is the model
    instance the action was about (optional); `details` is any extra
    structured data worth keeping, e.g. old and new values.
    """
    return ActivityLog.objects.create(
        school=school,
        actor=actor if actor is not None and actor.is_authenticated else None,
        actor_name=display_name(actor) if actor is not None and actor.is_authenticated else "System",
        action=action,
        summary=summary[:500],
        target_type=target._meta.model_name if target is not None else "",
        target_id=target.pk if target is not None else None,
        details=details,
    )
