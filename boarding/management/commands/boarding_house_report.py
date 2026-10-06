"""
Counts only: how many boarding houses have roll call history (so can only be archived, not deleted).

  python manage.py boarding_house_report
"""
from django.core.management.base import BaseCommand
from django.db.models import Count

from boarding.models import BoardingHouse


class Command(BaseCommand):
    help = "Report how many boarding houses have history (read-only)."

    def handle(self, *args, **options):
        houses = BoardingHouse.objects.annotate(calls=Count("roll_calls"))
        total = houses.count()
        with_history = houses.filter(calls__gt=0).count()
        self.stdout.write(f"{total} boarding house(s); {with_history} with roll call history "
                          f"(these can't be deleted any more, only archived); {houses.filter(is_archived=True).count()} archived.")
