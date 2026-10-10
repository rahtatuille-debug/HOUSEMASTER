"""
M-Pesa (owner's request, 2026-10-09).

Two kinds of money, each to its own account:
- School fees: each school connects its own paybill or till (MpesaAccount).
  Parents press "Pay with M-Pesa" (a PIN prompt on their phone), or pay the
  paybill directly with the student's admission number as the account; both
  are recorded as fee payments with a receipt, without the bursar.
- Subscriptions: schools pay the HouseMaster owner's paybill (set in the
  server's environment, not here) the same two ways, which marks the
  invoice paid.

Safaricom calls us back at URLs with a long random token in them, so a
caller has to know it. The keys are stored encrypted and never sent back.
Phone numbers are kept masked.
"""
import secrets

from django.conf import settings
from django.db import models

from students.models import School, Student


def new_token():
    # Letters a-f and digits only: Safaricom never calls an address containing words like "exe" or "sql".
    return secrets.token_hex(20)


class MpesaAccount(models.Model):
    class Kind(models.TextChoices):
        PAYBILL = "paybill", "Paybill"
        TILL = "till", "Till (Buy Goods)"

    class Environment(models.TextChoices):
        SANDBOX = "sandbox", "Sandbox (testing)"
        PRODUCTION = "production", "Live"

    school = models.OneToOneField(School, on_delete=models.CASCADE, related_name="mpesa_account")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.PAYBILL)
    # A paybill's number; for a till, the store (head office) number M-Pesa gave with the till.
    shortcode = models.CharField(max_length=10)
    till_number = models.CharField(max_length=10, blank=True)
    environment = models.CharField(max_length=10, choices=Environment.choices, default=Environment.SANDBOX)
    consumer_key = models.TextField(blank=True)  # encrypted (mpesa.secrets)
    consumer_secret = models.TextField(blank=True)
    passkey = models.TextField(blank=True)
    callback_token = models.CharField(max_length=64, unique=True, default=new_token)
    enabled = models.BooleanField(default=True)
    c2b_registered_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class StkRequest(models.Model):
    """One "Pay with M-Pesa" prompt sent to a phone."""

    class Purpose(models.TextChoices):
        FEES = "fees", "School fees"
        SUBSCRIPTION = "subscription", "HouseMaster subscription"

    class Status(models.TextChoices):
        PENDING = "pending", "Waiting for the payer"
        PAID = "paid", "Paid"
        FAILED = "failed", "Not paid"

    purpose = models.CharField(max_length=15, choices=Purpose.choices)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="stk_requests")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, null=True, blank=True, related_name="stk_requests")
    invoice = models.ForeignKey("billing.Invoice", on_delete=models.CASCADE, null=True, blank=True, related_name="stk_requests")
    amount = models.PositiveIntegerField()
    phone_masked = models.CharField(max_length=20)
    account_reference = models.CharField(max_length=20)
    merchant_request_id = models.CharField(max_length=100, blank=True)
    checkout_request_id = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    result_description = models.CharField(max_length=255, blank=True)
    receipt = models.CharField(max_length=30, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    requested_by_name = models.CharField(max_length=150, blank=True)
    fee_payment = models.OneToOneField("fees.Payment", on_delete=models.SET_NULL, null=True, blank=True, related_name="stk_request")
    created_at = models.DateTimeField(auto_now_add=True)
    checked_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)


class C2BPayment(models.Model):
    """A payment made straight to a paybill or till, as M-Pesa confirmed it."""

    class Status(models.TextChoices):
        RECORDED = "recorded", "Recorded"
        UNMATCHED = "unmatched", "Needs a student"
        IGNORED = "ignored", "Not for fees"

    purpose = models.CharField(max_length=15, choices=StkRequest.Purpose.choices)
    school = models.ForeignKey(School, on_delete=models.CASCADE, null=True, blank=True, related_name="c2b_payments")
    trans_id = models.CharField(max_length=30, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    bill_ref = models.CharField(max_length=60, blank=True)
    payer_name = models.CharField(max_length=150, blank=True)
    phone_masked = models.CharField(max_length=20, blank=True)
    paid_at = models.DateTimeField()
    status = models.CharField(max_length=10, choices=Status.choices)
    student = models.ForeignKey(Student, on_delete=models.SET_NULL, null=True, blank=True, related_name="c2b_payments")
    fee_payment = models.OneToOneField("fees.Payment", on_delete=models.SET_NULL, null=True, blank=True, related_name="c2b_payment")
    invoice = models.ForeignKey("billing.Invoice", on_delete=models.SET_NULL, null=True, blank=True, related_name="c2b_payments")
    handled_by_name = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_at", "-id"]
