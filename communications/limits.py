"""
Limits on urgent alerts (B-9).

A school can send ALERT_SCHOOL_RATE real alerts (default 10 a day) and,
separately, ALERT_TEST_SCHOOL_RATE test alerts (default 5 a day), so a
stolen admin login can't flood every parent and testing never uses up the
budget for a real emergency. The budget is checked only once an alert has
passed every other check, and used only once it is saved, so a refused or
invalid alert costs nothing.
"""
from rest_framework.exceptions import Throttled
from rest_framework.throttling import SimpleRateThrottle


class _SchoolAlertThrottle(SimpleRateThrottle):
    """Counts per school. Not a view throttle: see check_alert_budget."""

    def key_for(self, school):
        return self.cache_format % {"scope": self.scope, "ident": school.pk}

    def get_cache_key(self, request, view):
        return None


class AlertSchoolThrottle(_SchoolAlertThrottle):
    scope = "alert_school"


class TestAlertSchoolThrottle(_SchoolAlertThrottle):
    scope = "alert_test_school"


def check_alert_budget(school, is_test):
    """
    Raises Throttled (429 with Retry-After) when the school has used up its
    alerts; otherwise returns a function to call once the alert is saved,
    which counts it (DRF's own bookkeeping).
    """
    throttle = (TestAlertSchoolThrottle if is_test else AlertSchoolThrottle)()
    if throttle.rate is None:
        return lambda: None
    throttle.key, throttle.now = throttle.key_for(school), throttle.timer()
    throttle.history = [t for t in throttle.cache.get(throttle.key, []) if t > throttle.now - throttle.duration]
    if len(throttle.history) >= throttle.num_requests:
        raise Throttled(wait=throttle.wait(), detail=(
            "Your school has sent as many test alerts as it can for now." if is_test else
            "Your school has sent as many urgent alerts as it can for now. If this is a real emergency, "
            "phone or message people directly."))
    return throttle.throttle_success
