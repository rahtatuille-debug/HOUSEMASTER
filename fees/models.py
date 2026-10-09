"""
School fees (owner's request, 2026-10-09).

The school sets fee items for each term (tuition, boarding, lunch...), for
every year group or one, and for everyone, boarders or day students. "Bill
the term" charges each matching student once. The bursar adds extras and
discounts (bursaries) per student and records payments by hand; each payment
gets a receipt number and its receipt is emailed to the parents.

Parents see their child's balance, charges and receipts, and can say "we've
paid" with the payment's reference; the bursar confirms it, which records
the payment. Nothing is deleted: a payment entered by mistake is voided,
with the reason, so the receipts stay in sequence.
"""
from django.conf import settings
from django.db import models

from gradebook.models import Term
from students.models import School, Student, YearGroup

METHODS = [("mpesa", "M-Pesa"), ("bank", "Bank transfer"), ("cash", "Cash"), ("cheque", "Cheque"),
           ("card", "Card"), ("other", "Other")]


class FeeSettings(models.Model):
    school = models.OneToOneField(School, on_delete=models.CASCADE, related_name="fee_settings")
    currency = models.CharField(max_length=3, default="KES")
    payment_instructions = models.TextField(blank=True, help_text="Shown to parents, e.g. the paybill and account.")
    next_receipt = models.PositiveIntegerField(default=1)


class FeeItem(models.Model):
    class AppliesTo(models.TextChoices):
        ALL = "all", "Everyone"
        BOARDING = "boarding", "Boarders only"
        DAY = "day", "Day students only"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="fee_items")
    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name="fee_items")
    name = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    year_group = models.ForeignKey(YearGroup, on_delete=models.CASCADE, null=True, blank=True, related_name="fee_items",
                                   help_text="Blank for every year group.")
    applies_to = models.CharField(max_length=10, choices=AppliesTo.choices, default=AppliesTo.ALL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["term_id", "year_group_id", "name", "id"]


class Charge(models.Model):
    class Kind(models.TextChoices):
        FEE = "fee", "Fee"
        EXTRA = "extra", "Extra charge"
        DISCOUNT = "discount", "Discount or bursary"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="fee_charges")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="fee_charges")
    term = models.ForeignKey(Term, on_delete=models.SET_NULL, null=True, blank=True, related_name="fee_charges")
    item = models.ForeignKey(FeeItem, on_delete=models.SET_NULL, null=True, blank=True, related_name="charges")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.FEE)
    description = models.CharField(max_length=150)
    # Negative for a discount or bursary.
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    created_by_name = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [models.UniqueConstraint(fields=["student", "item"], condition=models.Q(item__isnull=False),
                                               name="one_charge_per_fee_item")]


class Payment(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="fee_payments")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="fee_payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_on = models.DateField()
    method = models.CharField(max_length=10, choices=METHODS)
    reference = models.CharField(max_length=100, blank=True)
    payer_name = models.CharField(max_length=150, blank=True)
    receipt_number = models.CharField(max_length=30)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    recorded_by_name = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=200, blank=True)
    voided_by_name = models.CharField(max_length=150, blank=True)

    class Meta:
        ordering = ["paid_on", "id"]
        constraints = [models.UniqueConstraint(fields=["school", "receipt_number"], name="one_receipt_number")]


class PaymentClaim(models.Model):
    """A parent saying they've paid; the bursar confirms it (recording the payment) or says why not."""

    class Status(models.TextChoices):
        OPEN = "open", "Waiting to be checked"
        CONFIRMED = "confirmed", "Confirmed"
        REJECTED = "rejected", "Not found"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="fee_claims")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="fee_claims")
    claimed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    claimed_by_name = models.CharField(max_length=150)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_on = models.DateField()
    method = models.CharField(max_length=10, choices=METHODS)
    reference = models.CharField(max_length=100)
    note = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    decided_by_name = models.CharField(max_length=150, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.CharField(max_length=200, blank=True)
    payment = models.OneToOneField(Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name="claim")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
