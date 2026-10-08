"""Making student logins, and who the signed-in student is."""
import re
import secrets
import unicodedata

from django.contrib.auth import get_user_model

from accounts.scoping import can_manage_parents, is_leader

from .models import StudentAccount

# Short, friendly words for starting passwords a student can type from a printed slip.
WORDS = (
    "apple badge beach bench berry bird boat book brave bread brick bridge brook brush cabin camel candle canoe "
    "cedar chalk cheer chess cliff cloud clover coast comet coral cotton crane crown daisy delta dolphin dream drum "
    "eagle earth ember falcon fern field flame flute forest fox frost garden giant glade globe grape grass harbor "
    "hazel hill honey horse island ivory jolly kettle kite lake lantern lemon lily lion maple meadow melon mint "
    "moon moss nectar nest noble ocean olive orbit otter panda paper peach pearl pebble pepper piano pine planet "
    "plum pony prism quail quest rabbit rain raven reef ribbon river robin rocket rose ruby sail sand seal shell "
    "silver sky snow spark spring star stone storm sugar summit sun swan tiger topaz tower trail tulip valley "
    "violet wave whale willow wind wolf zebra"
).split()


def can_manage(user):
    """Admins, leadership and the secretary make and manage student accounts."""
    return hasattr(user, "profile") and (is_leader(user) or can_manage_parents(user))


def account_of(user):
    """The StudentAccount for a signed-in student, or None for anyone else."""
    try:
        return user.student_account
    except (StudentAccount.DoesNotExist, AttributeError):
        return None


def _ascii(text):
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower())


def new_username(student):
    """e.g. amina.k4821: no @, so it can never be mistaken for an email; unique across HouseMaster."""
    base = f"{_ascii(student.first_name)[:12] or 'student'}.{_ascii(student.last_name)[:1] or 's'}"
    users = get_user_model().objects
    while True:
        username = f"{base}{secrets.randbelow(9000) + 1000}"
        if not users.filter(username__iexact=username).exists():
            return username


def new_password():
    """e.g. river-tiger-47: easy to type from a slip, changed at first sign-in."""
    return f"{secrets.choice(WORDS)}-{secrets.choice(WORDS)}-{secrets.randbelow(90) + 10}"


def create(student, created_by_name):
    """Returns (account, starting password)."""
    password = new_password()
    user = get_user_model().objects.create_user(username=new_username(student), email="", password=password,
                                                first_name=student.first_name, last_name=student.last_name)
    account = StudentAccount.objects.create(student=student, user=user, created_by_name=created_by_name)
    return account, password


def reset(account):
    """A new starting password; every session the student had open ends."""
    password = new_password()
    account.user.set_password(password)
    account.user.save()
    account.must_change_password = True
    account.save(update_fields=["must_change_password"])
    return password
