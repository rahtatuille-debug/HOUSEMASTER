"""
Monthly subscriptions. Each school pays by the month: a price per active
student (the owner's choice, KES 50), or a flat price for a size tier. Payments are recorded by hand by the HouseMaster
owner in the Django admin; HouseMaster issues invoices, sends reminders, and
locks a school whose invoice is still unpaid when the grace period ends.

A plan without a price, or a school with no students yet, is never invoiced. An exempt school (demo, partner,
or a school that was here before subscriptions) is never invoiced or locked.
"""
from django.conf import settings
from django.db import models

from students.models import School


class Plan(models.Model):
    name = models.CharField(max_length=60)
    max_students = models.PositiveIntegerField(null=True, blank=True, help_text="Blank for no limit (the biggest tier).")
    monthly_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                        help_text="A flat price a month. Blank: charged per student instead (below), or not at all.")
    price_per_student = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                            help_text="A month, for each active student. Used when there's no flat price.")
    currency = models.CharField(max_length=3, default="KES")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = [models.F("max_students").asc(nulls_last=True)]

    def amount_for(self, students):
        """The month's price for this many students, or None when the plan has no price."""
        if self.monthly_price is not None:
            return self.monthly_price
        if self.price_per_student is not None:
            return self.price_per_student * students
        return None

    def __str__(self):
        limit = f"up to {self.max_students}" if self.max_students else "any size"
        return f"{self.name} ({limit} students)"


class Subscription(models.Model):
    school = models.OneToOneField(School, on_delete=models.CASCADE, related_name="subscription")
    exempt = models.BooleanField(default=False, help_text="Never invoiced or locked (demo, partner, or a founding school).")
    grace_days = models.PositiveSmallIntegerField(default=14, help_text="Days after an invoice is due before the school is locked.")
    billing_email = models.EmailField(blank=True, help_text="Also gets invoices and reminders (the school's admins always do).")
    owner_notes = models.TextField(blank=True, help_text="For you only; the school never sees it.")
    # Kept up to date whenever invoices change (services.refresh): the day the school is locked, if an
    # invoice stays unpaid. The sign-in gate reads only this, so it costs one query.
    locked_from = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.school.name}{' (exempt)' if self.exempt else ''}"


class Invoice(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Unpaid"
        PAID = "paid", "Paid"
        VOID = "void", "Cancelled"

    class Method(models.TextChoices):
        MPESA = "mpesa", "M-Pesa"
        BANK = "bank", "Bank transfer"
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        OTHER = "other", "Other"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="invoices")
    number = models.CharField(max_length=30, unique=True)
    plan_name = models.CharField(max_length=60)
    students = models.PositiveIntegerField(help_text="Active students when it was issued.")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    period_start = models.DateField()
    period_end = models.DateField()
    issued_on = models.DateField()
    due_on = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    paid_on = models.DateField(null=True, blank=True)
    payment_method = models.CharField(max_length=10, choices=Method.choices, blank=True)
    payment_reference = models.CharField(max_length=100, blank=True)
    # The school telling you it has paid (it doesn't mark it paid: you do).
    school_reported_at = models.DateTimeField(null=True, blank=True)
    school_report = models.CharField(max_length=500, blank=True)
    reminders_sent = models.JSONField(default=list, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period_start", "-id"]

    def __str__(self):
        return f"{self.number} {self.school.name} {self.currency} {self.amount} ({self.get_status_display()})"
