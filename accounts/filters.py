import django_filters
from django.db import models
from django_filters.rest_framework import DjangoFilterBackend, FilterSet


class IdFilterSet(FilterSet):
    """
    Filters on linked records (?student=, ?term=, ...) as plain IDs.

    django-filter's default checks the ID exists anywhere in the database
    and answers 400 if it doesn't, which would let one school tell whether
    an ID belongs to another school (empty list) or to nobody (400). Plain
    ID filters just return an empty list for both. The queryset is already
    limited to the requester's school, so nothing else changes.
    """

    FILTER_DEFAULTS = {
        **FilterSet.FILTER_DEFAULTS,
        models.ForeignKey: {"filter_class": django_filters.NumberFilter},
        models.OneToOneField: {"filter_class": django_filters.NumberFilter},
    }


class SchoolSafeFilterBackend(DjangoFilterBackend):
    filterset_base = IdFilterSet
