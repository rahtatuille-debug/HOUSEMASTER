"""
One login, several schools: a person can be staff at one school, staff at another and a parent at a third, with
one email and one password. Each place is a membership: a staff Profile or a parent Guardian, one per school.

A session acts as one membership at a time. Its tokens carry it in the `mem` claim ("staff:12", "parent:7"), and
VersionedJWTAuthentication makes it the request's `user.profile` (staff) or `user.guardian` (parent), never both,
so every view keeps working exactly as it did when a login belonged to one school. Switching membership issues new
tokens (POST /api/account/switch/).

For other users (a message's sender, a class's parents), `user.profile` / `user.guardian` is their membership at the
school the request is acting for, falling back to their first one.
"""
from contextvars import ContextVar

from django.core.exceptions import ObjectDoesNotExist

MEMBERSHIP_CLAIM = "mem"
STAFF, PARENT = "staff", "parent"

# The school the current request acts for, set by VersionedJWTAuthentication and cleared by
# housemaster.middleware.CurrentSchoolMiddleware at the start of each request.
current_school = ContextVar("housemaster_current_school", default=None)


class NoMembership(ObjectDoesNotExist, AttributeError):
    """`user.profile` / `user.guardian` when there isn't one: like Django's RelatedObjectDoesNotExist, it is an
    AttributeError, so getattr(user, "profile", None) and hasattr() keep working."""


CACHE = {STAFF: "_hm_profiles", PARENT: "_hm_guardians"}
RELATED = {STAFF: "profiles", PARENT: "guardian_memberships"}
ACTIVE = "_hm_active"  # (kind, membership) chosen for a request


def _rows(user, kind):
    prefetched = getattr(user, "_prefetched_objects_cache", {}).get(RELATED[kind])
    if prefetched is not None:
        return sorted(prefetched, key=lambda m: m.pk)
    if CACHE[kind] not in user.__dict__:
        user.__dict__[CACHE[kind]] = list(getattr(user, RELATED[kind]).order_by("id")) if user.pk else []
    return user.__dict__[CACHE[kind]]


def forget(user, keep_active=True):
    """Drop what was looked up for this user object (after a membership is added, changed or removed). The
    membership a request acts as stays, so saving it mid-request never turns a parent session into staff."""
    for key in (*CACHE.values(), *(() if keep_active else (ACTIVE,))):
        user.__dict__.pop(key, None)


def _membership(user, kind):
    chosen = user.__dict__.get(ACTIVE)
    if chosen is not None:
        if chosen[0] == kind:
            return chosen[1]
        raise NoMembership(f"This session isn't acting as {kind}.")
    rows = _rows(user, kind)
    if not rows:
        raise NoMembership(f"No {kind} membership.")
    school = current_school.get()
    return next((m for m in rows if m.school_id == school), rows[0])


def profile_of(user):
    return _membership(user, STAFF)


def guardian_of(user):
    return _membership(user, PARENT)


def key_of(membership):
    from .models import Profile

    return f"{STAFF if isinstance(membership, Profile) else PARENT}:{membership.pk}"


def all_memberships(user):
    """Every active membership this login has, staff first, each school in the order they joined."""
    from guardians.models import Guardian

    from .models import Profile

    staff = Profile.objects.filter(user=user, is_active=True).select_related("school").order_by("id")
    parent = Guardian.objects.filter(user=user, is_active=True).select_related("school").order_by("id")
    return [*staff, *parent]


def find(user, key):
    """The user's active membership for a claim like "staff:12", or None."""
    from guardians.models import Guardian

    from .models import Profile

    kind, _, pk = (key or "").partition(":")
    model = {STAFF: Profile, PARENT: Guardian}.get(kind)
    if model is None or not pk.isdigit():
        return None
    return model.objects.filter(pk=int(pk), user=user, is_active=True).select_related("school").first()


def default_for(user):
    """The membership a new sign-in starts in: the one used last, else the first staff one, else a parent one."""
    from .models import UserSecurity

    last = UserSecurity.objects.filter(user=user).values_list("last_membership", flat=True).first()
    chosen = find(user, last) if last else None
    if chosen is None:
        memberships = all_memberships(user)
        chosen = memberships[0] if memberships else None
    return chosen


def act_as(user, membership):
    """Make `membership` this user object's profile or guardian (for the rest of the request)."""
    from .models import Profile

    forget(user, keep_active=False)
    if membership is None:
        user.__dict__[ACTIVE] = ("none", None)
        return
    kind = STAFF if isinstance(membership, Profile) else PARENT
    membership.user = user
    user.__dict__[ACTIVE] = (kind, membership)
    current_school.set(membership.school_id)


def remember(user, membership):
    from .models import UserSecurity

    UserSecurity.objects.update_or_create(user=user, defaults={"last_membership": key_of(membership)})


def describe(membership, current=None):
    from .models import Profile

    staff = isinstance(membership, Profile)
    return {
        "key": key_of(membership),
        "kind": STAFF if staff else PARENT,
        "school": membership.school.name,
        "school_id": membership.school_id,
        "role": membership.get_role_display() if staff else "Parent",
        "current": current is not None and key_of(current) == key_of(membership),
    }


def set_active(membership, active):
    """Deactivate or reactivate one school's membership. The login stays open while it has another active one; a
    session acting as this membership ends straight away (VersionedJWTAuthentication finds it inactive)."""
    from guardians.models import Guardian

    from .models import Profile

    membership.is_active = active
    membership.save(update_fields=["is_active"])
    user = membership.user
    others = (Profile.objects.filter(user=user, is_active=True).exists()
              or Guardian.objects.filter(user=user, is_active=True).exists())
    if user.is_active != others:
        user.is_active = others
        user.save(update_fields=["is_active"])


def install():
    """Give User the `profile` and `guardian` attributes (accounts.apps)."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    User.profile = property(profile_of)
    User.guardian = property(guardian_of)
