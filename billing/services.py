"""Pricing, invoices, reminders and locking (see billing.models)."""
import calendar
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Max

from students.localtime import school_localdate
from students.models import Student

from .models import Invoice, Plan, Subscription

ISSUE_DAYS_AHEAD = 7  # invoice a month this many days before it starts


def subscription_for(school):
    return Subscription.objects.get_or_create(school=school)[0]


def make_exempt(school, note="Demo school."):
    Subscription.objects.update_or_create(school=school, defaults={"exempt": True, "owner_notes": note, "locked_from": None})


def active_students(school):
    return Student.objects.filter(school=school, is_active=True).count()


def tier_for(count):
    """The smallest active tier that fits this many students (the biggest one has no limit)."""
    plans = list(Plan.objects.filter(is_active=True))
    for plan in plans:
        if plan.max_students is None or count <= plan.max_students:
            return plan
    return plans[-1] if plans else None


def add_month(day):
    """The same day next month (or the month's last day), e.g. 31 Jan -> 28 Feb."""
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


def paid_until(school):
    return Invoice.objects.filter(school=school, status=Invoice.Status.PAID).aggregate(d=Max("period_end"))["d"]


def refresh(school):
    """Recompute the lock date: the oldest unpaid invoice's due date plus the grace period."""
    sub = subscription_for(school)
    oldest = (Invoice.objects.filter(school=school, status=Invoice.Status.OPEN).order_by("due_on").first()
              if not sub.exempt else None)
    locked_from = oldest.due_on + timedelta(days=sub.grace_days) if oldest else None
    if sub.locked_from != locked_from:
        sub.locked_from = locked_from
        sub.save(update_fields=["locked_from"])
    return sub


def status(school, today=None):
    """
    {status: exempt|active|due|overdue|locked, ...} for the school's Billing page and banners.
    due: an invoice is unpaid but not yet due; overdue: past due, in the grace period; locked: grace is over.
    """
    sub = subscription_for(school)
    today = today or school_localdate(school)
    if sub.exempt:
        return {"status": "exempt", "label": "Free", "locked_from": None, "days_left": None, "invoice": None}
    oldest = Invoice.objects.filter(school=school, status=Invoice.Status.OPEN).order_by("due_on").first()
    if oldest is None:
        return {"status": "active", "label": "Paid up", "locked_from": None, "days_left": None, "invoice": None}
    locked_from = oldest.due_on + timedelta(days=sub.grace_days)
    if today >= locked_from:
        state, label, days = "locked", "Locked: payment overdue", 0
    elif today > oldest.due_on:
        state, label, days = "overdue", "Payment overdue", (locked_from - today).days
    else:
        state, label, days = "due", "Payment due", (oldest.due_on - today).days
    return {"status": state, "label": label, "locked_from": locked_from, "days_left": days, "invoice": oldest.id}


def is_locked(school_id, today):
    """For the sign-in gate: one query."""
    row = Subscription.objects.filter(school_id=school_id).values("exempt", "locked_from").first()
    return bool(row and not row["exempt"] and row["locked_from"] and today >= row["locked_from"])


def _number(school, start):
    prefix = f"HM-{start:%Y%m}-{school.id:04d}"
    n = Invoice.objects.filter(number__startswith=prefix).count() + 1
    return f"{prefix}-{n}"


def next_period_start(school):
    """The day after the last invoiced month; a school's first month starts the day it's invoiced."""
    last = Invoice.objects.filter(school=school).exclude(status=Invoice.Status.VOID).aggregate(d=Max("period_end"))["d"]
    return last + timedelta(days=1) if last else school_localdate(school)


def issue_due(school, today=None):
    """
    Issue the next month's invoice when it starts within a week (a new school: straight away), at the
    school's price (per student, or its tier's flat price). Nothing for exempt schools, a plan without a
    price or a school with no students yet. Returns the invoice or None.
    """
    sub = subscription_for(school)
    today = today or school_localdate(school)
    if sub.exempt:
        return None
    start = next_period_start(school)
    if start - timedelta(days=ISSUE_DAYS_AHEAD) > today:
        return None
    count = active_students(school)
    plan = tier_for(count)
    amount = plan.amount_for(count) if plan else None
    if not amount:
        return None
    with transaction.atomic():
        invoice = Invoice.objects.create(
            school=school, number=_number(school, start), plan_name=plan.name, students=count,
            amount=amount, currency=plan.currency, period_start=start,
            period_end=add_month(start) - timedelta(days=1), issued_on=today, due_on=max(start, today))
        refresh(school)
    email_school(invoice, "issued")
    return invoice


def record_payment(invoice, paid_on, method, reference, by=None):
    """Mark an invoice paid (the owner, in the admin) and tell the school."""
    invoice.status = Invoice.Status.PAID
    invoice.paid_on = paid_on
    invoice.payment_method = method
    invoice.payment_reference = reference[:100]
    invoice.recorded_by = by
    invoice.save()
    refresh(invoice.school)
    email_school(invoice, "paid")


# Emails -------------------------------------------------------------------

def recipients(school):
    from accounts.models import Profile

    sub = subscription_for(school)
    emails = list(Profile.objects.filter(school=school, role=Profile.Role.ADMIN, user__is_active=True)
                  .exclude(user__email="").values_list("user__email", flat=True))
    if sub.billing_email and sub.billing_email.lower() not in {e.lower() for e in emails}:
        emails.append(sub.billing_email)
    return emails


def _money(invoice):
    return f"{invoice.currency} {invoice.amount:,.2f}"


def email_school(invoice, kind):
    """kind: issued, reminder, overdue, lock_soon, locked, paid."""
    from guardians.notifications import send_after_commit

    school = invoice.school
    sub = subscription_for(school)
    lock_day = invoice.due_on + timedelta(days=sub.grace_days)
    how = settings.BILLING_PAYMENT_INSTRUCTIONS.strip()
    pay = f"\n\nHow to pay: {how}\nPlease use the invoice number {invoice.number} as the reference." if how else ""
    period = f"{invoice.period_start:%d %B %Y} to {invoice.period_end:%d %B %Y}"
    subject, body = {
        "issued": (f"HouseMaster invoice {invoice.number}: {_money(invoice)}",
                   f"Your HouseMaster subscription invoice for {period} ({invoice.plan_name} plan, {invoice.students} "
                   f"students) is {_money(invoice)}, due on {invoice.due_on:%d %B %Y}.{pay}"),
        "reminder": (f"Reminder: HouseMaster invoice {invoice.number} is due on {invoice.due_on:%d %B}",
                     f"Invoice {invoice.number} for {_money(invoice)} is due on {invoice.due_on:%d %B %Y}.{pay}"),
        "overdue": (f"HouseMaster invoice {invoice.number} is overdue",
                    f"Invoice {invoice.number} for {_money(invoice)} was due on {invoice.due_on:%d %B %Y}. If it isn't "
                    f"paid by {lock_day:%d %B %Y}, HouseMaster will be locked for your school until it is.{pay}"),
        "lock_soon": (f"HouseMaster will be locked on {lock_day:%d %B} unless invoice {invoice.number} is paid",
                      f"Invoice {invoice.number} for {_money(invoice)} is still unpaid. On {lock_day:%d %B %Y} your "
                      f"staff, parents and students will no longer be able to use HouseMaster until it is paid. "
                      f"Your data is kept safe.{pay}"),
        "locked": (f"HouseMaster is locked for {school.name}",
                   f"Invoice {invoice.number} for {_money(invoice)} is unpaid, so HouseMaster is locked for your "
                   f"school. Admins can still sign in to see the invoice. Everything is unlocked as soon as the "
                   f"payment is recorded, and no data has been lost.{pay}"),
        "paid": (f"Thank you: payment received for {invoice.number}",
                 f"We have recorded your payment of {_money(invoice)} for {period}. Thank you."),
    }[kind]
    body = f"{body}\n\nSee your invoices on the Billing page: {settings.FRONTEND_URL}\n\nHouseMaster"
    messages = [(subject, body, email) for email in recipients(school)]
    if messages:
        send_after_commit(messages)
    return len(messages)


def send_reminders(today=None):
    """Once each: three days before due, the day after due, three days before locking, and on locking."""
    sent = 0
    for invoice in Invoice.objects.filter(status=Invoice.Status.OPEN).select_related("school"):
        sub = subscription_for(invoice.school)
        if sub.exempt:
            continue
        day = today or school_localdate(invoice.school)
        lock_day = invoice.due_on + timedelta(days=sub.grace_days)
        due = [k for k, when in (("reminder", invoice.due_on - timedelta(days=3)), ("overdue", invoice.due_on + timedelta(days=1)),
                                 ("lock_soon", lock_day - timedelta(days=3)), ("locked", lock_day))
               if day >= when and k not in invoice.reminders_sent]
        if due:
            kind = due[-1]  # only the latest that applies; the earlier ones are past
            email_school(invoice, kind)
            invoice.reminders_sent = [*invoice.reminders_sent, *due]
            invoice.save(update_fields=["reminders_sent"])
            sent += 1
    return sent


def tell_owner(invoice, method, reference, note):
    """A school says it has paid: email the owner to check and record it."""
    from guardians.notifications import send_after_commit

    if not settings.BILLING_OWNER_EMAIL:
        return 0
    send_after_commit([(
        f"{invoice.school.name} says it paid {invoice.number}",
        f"{invoice.school.name} says it has paid invoice {invoice.number} ({_money(invoice)}).\n\n"
        f"Method: {method or 'not given'}\nReference: {reference or 'not given'}\nNote: {note or '—'}\n\n"
        f"Check it, then record the payment in the HouseMaster admin (Billing > Invoices).",
        settings.BILLING_OWNER_EMAIL,
    )])
    return 1
