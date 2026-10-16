"""Fee charges, balances, payments, receipts and emails to parents (see fees.models)."""
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from activity.services import display_name, log_activity, student_name
from students.models import Student

from .models import Charge, FeeItem, FeeSettings, Payment, PaymentClaim

CURRENCY_BY_COUNTRY = {"ke": "KES", "gb": "GBP", "us": "USD"}


def settings_for(school):
    row = FeeSettings.objects.filter(school=school).first()
    if row is None:
        try:
            with transaction.atomic():
                row = FeeSettings.objects.create(school=school, currency=CURRENCY_BY_COUNTRY.get(school.country, "KES"))
        except IntegrityError:  # created by another request at the same moment (two first payments at once)
            row = FeeSettings.objects.get(school=school)
    return row


def money(amount, currency):
    return f"{currency} {Decimal(amount):,.2f}"


def balances(students):
    """{student_id: (charged, paid)} for these students, in two queries."""
    ids = [s.id if hasattr(s, "id") else s for s in students]
    charged = dict(Charge.objects.filter(student_id__in=ids).values("student_id").annotate(t=Sum("amount"))
                   .values_list("student_id", "t"))
    paid = dict(Payment.objects.filter(student_id__in=ids, voided_at__isnull=True).values("student_id")
                .annotate(t=Sum("amount")).values_list("student_id", "t"))
    zero = Decimal("0")
    return {i: (charged.get(i) or zero, paid.get(i) or zero) for i in ids}


def balance(student):
    charged, paid = balances([student])[student.id]
    return charged - paid


def students_for_item(item):
    students = Student.objects.filter(school=item.school, is_active=True)
    if item.year_group_id:
        students = students.filter(school_class__year_group_id=item.year_group_id)
    if item.applies_to == FeeItem.AppliesTo.BOARDING:
        students = students.filter(mode_of_learning="boarding")
    elif item.applies_to == FeeItem.AppliesTo.DAY:
        students = students.exclude(mode_of_learning="boarding")
    return students


def bill_term(term, user):
    """Charge every active student each of the term's fee items they don't have yet. Returns how many charges."""
    by = display_name(user)
    created = 0
    with transaction.atomic():
        for item in FeeItem.objects.filter(term=term):
            have = set(Charge.objects.filter(item=item).values_list("student_id", flat=True))
            new = [Charge(school=term.school, student_id=sid, term=term, item=item, kind=Charge.Kind.FEE,
                          description=item.name, amount=item.amount, created_by_name=by)
                   for sid in students_for_item(item).values_list("id", flat=True) if sid not in have]
            Charge.objects.bulk_create(new)
            created += len(new)
    if created:
        log_activity(school=term.school, actor=user, action="fees.billed",
                     summary=f"Billed {term.name}: {created} fee charges")
    return created


def _lock_school(school):
    """The school's fee settings row, locked until the transaction ends: payments for one school go one at a time."""
    return FeeSettings.objects.select_for_update().get(pk=settings_for(school).pk)


def _receipt_number(row, paid_on):
    number = f"R{paid_on:%Y}-{row.next_receipt:05d}"
    row.next_receipt += 1
    row.save(update_fields=["next_receipt"])
    return number


def mpesa_code(reference):
    return str(reference or "").strip().upper()[:100]


def recorded_with_code(school, code):
    """Payments that still count and carry this M-Pesa code."""
    return Payment.objects.filter(school=school, method="mpesa", reference__iexact=code, voided_at__isnull=True) \
        .select_related("student")


def _known_mpesa_amount(school, code):
    """What M-Pesa itself said this transaction was for, when HouseMaster has heard from M-Pesa about it."""
    from mpesa.models import C2BPayment, StkRequest

    c2b = C2BPayment.objects.filter(school=school, trans_id__iexact=code).first()
    if c2b:
        return c2b.amount
    stk = StkRequest.objects.filter(school=school, receipt__iexact=code, status=StkRequest.Status.PAID).first()
    return Decimal(stk.amount) if stk else None


class MpesaCodeUsed(ValidationError):
    """The M-Pesa code is already on a payment that counts."""


def _check_code(school, code, amount, shared):
    from mpesa.models import C2BPayment

    if C2BPayment.objects.filter(school=school, trans_id__iexact=code, status=C2BPayment.Status.UNMATCHED).exists():
        raise MpesaCodeUsed({"reference": [f"M-Pesa payment {code} is waiting on the M-Pesa page for a student. "
                                           "Assign it there instead, so it's recorded once."],
                             "mpesa_code_used": [code]})
    existing = list(recorded_with_code(school, code))
    if not existing:
        return
    currency = settings_for(school).currency
    already = ", ".join(f"receipt {p.receipt_number} for {student_name(p.student)} ({money(p.amount, currency)})"
                        for p in existing)
    if not shared:
        raise MpesaCodeUsed({"reference": [f"M-Pesa code {code} is already recorded: {already}. If one M-Pesa payment "
                                           "covered more than one child, record it again as shared."],
                             "mpesa_code_used": [code]})
    known = _known_mpesa_amount(school, code)
    total = sum((p.amount for p in existing), Decimal(0)) + Decimal(amount)
    if known is not None and total > known:
        raise MpesaCodeUsed({"amount": [f"M-Pesa says {code} was for {money(known, currency)}, and {already} already "
                                        "uses part of it. This would record more than was paid."]})


def record_payment(student, user, amount, paid_on, method, reference="", payer_name="", claim=None, notify=True,
                   by_name=None, duplicates="refuse"):
    """
    Records a payment and numbers its receipt. For an M-Pesa code that is already on a payment that counts:
    duplicates="refuse" raises MpesaCodeUsed (a person entered it); "shared" records it as part of the same
    M-Pesa payment, up to what M-Pesa said was paid (one payment for siblings); "existing" records nothing and
    returns the payment already there (M-Pesa telling us about the same payment twice).
    """
    if method == "mpesa":
        reference = mpesa_code(reference)
    with transaction.atomic():
        row = _lock_school(student.school)
        if method == "mpesa" and reference:
            if duplicates == "existing":
                found = recorded_with_code(student.school, reference).first()
                if found:
                    return found
            else:
                _check_code(student.school, reference, amount, shared=duplicates == "shared")
        payment = Payment.objects.create(
            school=student.school, student=student, amount=amount, paid_on=paid_on, method=method,
            reference=reference[:100], payer_name=payer_name[:150], receipt_number=_receipt_number(row, paid_on),
            recorded_by=user, recorded_by_name=by_name or display_name(user))
        if claim is not None:
            claim.status = PaymentClaim.Status.CONFIRMED
            claim.payment = payment
            claim.decided_by_name = display_name(user)
            claim.decided_at = timezone.now()
            claim.save(update_fields=["status", "payment", "decided_by_name", "decided_at"])
    if not notify:  # demo data
        return payment
    currency = settings_for(student.school).currency
    log_activity(school=student.school, actor=user, action="fees.payment", target=student,
                 summary=f"Recorded a payment of {money(amount, currency)} for {student_name(student)} "
                         f"(receipt {payment.receipt_number})")
    email_receipt(payment)
    return payment


def void_payment(payment, user, reason):
    """Cancels a payment once: two people pressing Void together cancel it once, and the second is told."""
    with transaction.atomic():
        locked = Payment.objects.select_for_update().get(pk=payment.pk)
        if locked.voided_at is not None:
            raise ValidationError({"detail": [f"Receipt {locked.receipt_number} was already cancelled."]})
        locked.voided_at = timezone.now()
        locked.void_reason = reason[:200]
        locked.voided_by_name = display_name(user)
        locked.save(update_fields=["voided_at", "void_reason", "voided_by_name"])
    log_activity(school=payment.school, actor=user, action="fees.void", target=payment.student,
                 summary=f"Voided receipt {payment.receipt_number} for {student_name(payment.student)}")


# Emails to parents ----------------------------------------------------------

def _parents(student):
    from guardians.models import Guardian

    return list(Guardian.objects.filter(students=student, email_notifications=True, user__is_active=True)
                .exclude(user__email="").select_related("user"))


def _footer(school):
    return (f"\n\nOpen HouseMaster to see the statement and download receipts: {settings.FRONTEND_URL}\n\n"
            f"You're receiving this because you have a parent account with {school.name}. "
            f"You can turn these emails off on your Profile page in HouseMaster.")


def email_receipt(payment):
    from guardians.notifications import send_after_commit

    student, school = payment.student, payment.school
    currency = settings_for(school).currency
    left = balance(student)
    owing = (f"The balance now is {money(left, currency)}." if left > 0
             else "The fees are fully paid." if left == 0 else f"You are {money(-left, currency)} in credit.")
    messages = [(
        f"Receipt {payment.receipt_number}: {money(payment.amount, currency)} for {student.first_name}",
        f"Dear {g.name},\n\n{school.name} has received {money(payment.amount, currency)} for "
        f"{student.first_name} {student.last_name}'s fees on {payment.paid_on:%d %B %Y} "
        f"({payment.get_method_display()}{', ' + payment.reference if payment.reference else ''}). "
        f"Receipt number: {payment.receipt_number}.\n\n{owing}" + _footer(school),
        g.user.email) for g in _parents(student)]
    if messages:
        send_after_commit(messages)
    return len(messages)


def email_balances(students, user):
    """Remind the parents of each student who owes. Returns how many emails."""
    from guardians.notifications import send_after_commit

    students = list(students)
    if not students:
        return 0
    school = students[0].school
    fee = settings_for(school)
    how = f"\n\nHow to pay: {fee.payment_instructions.strip()}" if fee.payment_instructions.strip() else ""
    sums = balances(students)
    messages = []
    for s in students:
        charged, paid = sums[s.id]
        owed = charged - paid
        if owed <= 0:
            continue
        messages += [(
            f"School fees for {s.first_name}: {money(owed, fee.currency)} to pay",
            f"Dear {g.name},\n\nThis is a reminder from {school.name}: the fees balance for {s.first_name} "
            f"{s.last_name} is {money(owed, fee.currency)}.{how}\n\nIf you have paid recently, thank you; "
            f"you can tell the school in HouseMaster so it can be checked." + _footer(school),
            g.user.email) for g in _parents(s)]
    if messages:
        send_after_commit(messages)
        log_activity(school=school, actor=user, action="fees.reminders",
                     summary=f"Emailed {len(messages)} fee balance reminders to parents")
    return len(messages)


def tell_bursars(claim):
    """A short email to whoever manages fees: a parent says they've paid."""
    from accounts.models import Profile, StaffRole
    from guardians.notifications import send_after_commit

    school = claim.school
    # The bursars, or the admins when the school has no bursar.
    staff = Profile.objects.filter(school=school, user__is_active=True).exclude(user__email="")
    bursars = staff.filter(staff_roles__role=StaffRole.Role.BURSAR)
    emails = set((bursars if bursars.exists() else staff.filter(role=Profile.Role.ADMIN))
                 .filter(email_notifications=True).values_list("user__email", flat=True))
    currency = settings_for(school).currency
    messages = [(
        f"Fees: {claim.claimed_by_name} says they've paid {money(claim.amount, currency)}",
        f"{claim.claimed_by_name} says they paid {money(claim.amount, currency)} for {claim.student.first_name} "
        f"{claim.student.last_name}'s fees on {claim.paid_on:%d %B %Y} ({claim.get_method_display()}, "
        f"reference {claim.reference}).\n\nCheck it against your statement, then confirm it in HouseMaster "
        f"(Fees, To confirm): {settings.FRONTEND_URL}",
        address) for address in sorted(emails)]
    if messages:
        send_after_commit(messages)
