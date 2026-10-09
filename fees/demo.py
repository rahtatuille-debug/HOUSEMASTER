"""Fees for a demo school: this term's items, billed, with some payments and a parent's claim (never real data)."""
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User

from gradebook.models import Term
from students.localtime import school_localdate

from . import services
from .models import FeeItem, PaymentClaim

ITEMS = [("Tuition", Decimal("18000"), "all"), ("Boarding", Decimal("14000"), "boarding"),
         ("Lunch", Decimal("4500"), "day"), ("Activity fee", Decimal("1500"), "all")]


def fill_demo(school, seed=13):
    """Returns how many payments were recorded (nothing when the school already has fee items)."""
    if FeeItem.objects.filter(school=school).exists():
        return 0
    today = school_localdate(school)
    term = (Term.objects.filter(school=school, start_date__lte=today, end_date__gte=today).first()
            or Term.objects.filter(school=school).order_by("-start_date", "-id").first())
    admin = User.objects.filter(profile__school=school, profile__role="admin").order_by("id").first()
    if term is None or admin is None:
        return 0
    fee = services.settings_for(school)
    fee.payment_instructions = ("M-Pesa Paybill 247247, account: the student's admission number. Or bank transfer to the school account."
                                if fee.currency == "KES" else "Bank transfer to the school account, with the student's name as the reference.")
    fee.save()
    # Shillings for a Kenyan school; a tenth of that elsewhere (pounds, dollars).
    scale = Decimal("1") if fee.currency == "KES" else Decimal("0.1")
    for name, amount, applies in ITEMS:
        FeeItem.objects.create(school=school, term=term, name=name, amount=amount * scale, applies_to=applies)
    services.bill_term(term, admin)
    rng = random.Random(seed)
    students = list(school.students.filter(is_active=True).order_by("id"))
    sums = services.balances(students)
    paid = 0
    for s in students:
        owed = sums[s.id][0]
        roll = rng.random()
        if roll < 0.45:  # paid in full
            amounts = [owed]
        elif roll < 0.8:  # part paid
            amounts = [(owed * Decimal(rng.choice(("0.5", "0.6", "0.75")))).quantize(Decimal("1"))]
        else:
            amounts = []
        for amount in amounts:
            payment = services.record_payment(
                s, admin, amount, today - timedelta(days=rng.randint(1, 40)), rng.choice(("mpesa", "mpesa", "bank", "cash")),
                f"Q{rng.randint(10**7, 10**8 - 1)}", "", notify=False)
            payment.recorded_by_name = "Bursar (demo)"
            payment.save(update_fields=["recorded_by_name"])
            paid += 1
    # A couple of parents saying they've paid, for the bursar to check.
    from guardians.models import Guardian

    for g in Guardian.objects.filter(school=school, students__is_active=True).order_by("id")[:2]:
        s = g.students.filter(is_active=True).first()
        PaymentClaim.objects.create(school=school, student=s, claimed_by=g.user, claimed_by_name=g.name,
                                    amount=Decimal("5000") * scale, paid_on=today - timedelta(days=1), method="mpesa",
                                    reference=f"S{rng.randint(10**7, 10**8 - 1)}")
    return paid
