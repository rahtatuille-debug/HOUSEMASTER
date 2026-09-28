"""
Each school's own clock (B-4).

A school's day starts at midnight where the school is, not in Nairobi and
not in UTC, so anything that asks "what is today?" for a particular school
uses these helpers. Places with no school in view (the retention command,
background jobs) keep Django's TIME_ZONE, Africa/Nairobi.
"""
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from django.conf import settings
from django.utils import timezone


@lru_cache(maxsize=1)
def valid_zones():
    return frozenset(available_timezones())


def school_zone(school):
    name = getattr(school, "timezone", "") or settings.TIME_ZONE
    if name not in valid_zones():
        name = settings.TIME_ZONE
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:  # pragma: no cover - tzdata is a dependency
        return ZoneInfo(settings.TIME_ZONE)


def school_now(school):
    """The current time on the school's clock."""
    return timezone.localtime(timezone.now(), school_zone(school))


def school_localdate(school):
    """Today's date where the school is."""
    return school_now(school).date()


def school_date(moment, school):
    """The date a stored moment (e.g. when a report was finalized) fell on at the school."""
    return timezone.localtime(moment, school_zone(school)).date()
