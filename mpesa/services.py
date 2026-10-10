"""Starting M-Pesa payments, settling them, and matching paybill payments (see mpesa.models)."""
import logging
import re
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import Throttled, ValidationError

from activity.services import display_name, log_activity, student_name
from students.localtime import school_localdate

from . import daraja
from .models import C2BPayment, MpesaAccount, StkRequest
from .secrets_box import unseal

logger = logging.getLogger(__name__)

MAX_AMOUNT = 250_000  # M-Pesa's limit for one payment
ASK_AGAIN_AFTER = timedelta(seconds=15)  # before asking M-Pesa how a prompt went
GIVE_UP_AFTER = timedelta(minutes=3)  # a prompt nobody answered
STARTS_PER_10_MIN = 5


# Phones and references ----------------------------------------------------------

def normalize_phone(raw):
    """07XX…, 01XX…, +2547XX… or 2547XX… -> 2547XXXXXXXX; anything else is refused."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif len(digits) == 9 and digits[0] in "17":
        digits = "254" + digits
    if not re.fullmatch(r"254[17]\d{8}", digits):
        raise ValidationError({"phone": ["Enter a Safaricom number, e.g. 0712 345 678."]})
    return digits


def mask(phone):
    phone = str(phone or "")
    return f"{phone[:4]}•••{phone[-3:]}" if len(phone) > 7 else phone


def student_account(student):
    """What a parent types as the account number: the admission number (letters and digits), or S<id>."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", student.external_id or "").upper()
    return cleaned[:12] if 0 < len(cleaned) <= 12 else f"S{student.id}"


def school_account(school):
    """The account number a school uses to pay its subscription."""
    return f"HM{school.id:04d}"


def _clean(ref):
    return re.sub(r"[^A-Za-z0-9]", "", str(ref or "")).upper()


def find_student(school, ref):
    from students.models import Student

    key = _clean(ref)
    if not key:
        return None
    if re.fullmatch(r"S\d+", key):
        found = Student.objects.filter(school=school, pk=int(key[1:])).first()
        if found:
            return found
    for s in Student.objects.filter(school=school).exclude(external_id="").only("id", "external_id", "school_id"):
        if _clean(s.external_id) == key:
            return s
    return None


# Credentials and callback addresses --------------------------------------------

def callback_base():
    base = (getattr(settings, "MPESA_CALLBACK_BASE_URL", "") or "").rstrip("/")
    if not base.startswith("https://"):
        raise ValidationError({"detail": ["M-Pesa isn't available yet: the server's MPESA_CALLBACK_BASE_URL isn't set."]})
    return base


def hook_urls(token):
    base = callback_base()
    urls = {"stk": f"{base}/api/payments/hooks/{token}/stk/", "confirmation": f"{base}/api/payments/hooks/{token}/c2b/confirm/",
            "validation": f"{base}/api/payments/hooks/{token}/c2b/validate/"}
    # Safaricom quietly never calls an address containing these words (any case), so refuse them up front.
    banned = next((w for w in BANNED_URL_WORDS if w in urls["stk"].lower()), None)
    if banned:
        raise ValidationError({"detail": [f"M-Pesa won't call an address containing \"{banned}\". Change "
                                          "MPESA_CALLBACK_BASE_URL or the callback token so it doesn't."]})
    return urls


BANNED_URL_WORDS = ("m-pesa", "mpesa", "safaricom", "exec", "exe", "cmd", "sql", "query")


def school_credentials(account):
    return daraja.Credentials(
        environment=account.environment, shortcode=account.shortcode, kind=account.kind, till_number=account.till_number,
        consumer_key=unseal(account.consumer_key), consumer_secret=unseal(account.consumer_secret),
        passkey=unseal(account.passkey))


def school_ready(school):
    account = MpesaAccount.objects.filter(school=school, enabled=True).first()
    return account if account and account.consumer_key and account.passkey and account.shortcode else None


def owner_ready():
    s = settings
    return bool(s.MPESA_SHORTCODE and s.MPESA_CONSUMER_KEY and s.MPESA_CONSUMER_SECRET and s.MPESA_PASSKEY
                and s.MPESA_OWNER_CALLBACK_TOKEN and s.MPESA_CALLBACK_BASE_URL)


def owner_credentials():
    s = settings
    return daraja.Credentials(environment=s.MPESA_ENVIRONMENT, shortcode=s.MPESA_SHORTCODE, kind="paybill",
                              consumer_key=s.MPESA_CONSUMER_KEY, consumer_secret=s.MPESA_CONSUMER_SECRET,
                              passkey=s.MPESA_PASSKEY)


def credentials_for(stk):
    if stk.purpose == StkRequest.Purpose.SUBSCRIPTION:
        return owner_credentials()
    return school_credentials(stk.school.mpesa_account)


# Starting a payment ---------------------------------------------------------------

def _limit(user):
    key = f"mpesa-start:{user.pk}"
    count = cache.get(key, 0)
    if count >= STARTS_PER_10_MIN:
        raise Throttled(detail="Too many payment requests. Please wait a few minutes and try again.")
    cache.set(key, count + 1, 600)


def _amount(value):
    try:
        amount = Decimal(str(value))
    except Exception:
        raise ValidationError({"amount": ["Enter an amount in shillings, e.g. 5000."]})
    if amount != amount.to_integral_value() or not 1 <= amount <= MAX_AMOUNT:
        raise ValidationError({"amount": [f"Enter whole shillings, from 1 to {MAX_AMOUNT:,}."]})
    return int(amount)


def _start(*, creds, token, purpose, school, user, phone, amount, reference, description, student=None, invoice=None):
    _limit(user)
    phone = normalize_phone(phone)
    try:
        merchant_id, checkout_id = daraja.stk_push(creds, phone=phone, amount=amount, account_reference=reference,
                                                   description=description, callback_url=hook_urls(token)["stk"])
    except daraja.DarajaError as err:
        raise ValidationError({"detail": [str(err)]})
    stk = StkRequest.objects.create(
        purpose=purpose, school=school, student=student, invoice=invoice, amount=amount, phone_masked=mask(phone),
        account_reference=reference, merchant_request_id=merchant_id, checkout_request_id=checkout_id,
        requested_by=user, requested_by_name=display_name(user) if not hasattr(user, "guardian") else user.guardian.name)
    log_activity(school=school, actor=user, action="mpesa.prompt", target=student,
                 summary=f"Sent an M-Pesa prompt for {'fees' if student else 'the subscription'} (KES {amount:,})"
                         + (f" for {student_name(student)}" if student else ""))
    return stk


def start_fee_payment(student, user, phone, amount):
    from fees.services import settings_for

    account = school_ready(student.school)
    if account is None:
        raise ValidationError({"detail": ["The school hasn't connected M-Pesa yet."]})
    if settings_for(student.school).currency != "KES":
        raise ValidationError({"detail": ["M-Pesa payments are in shillings, and this school's fees aren't."]})
    return _start(creds=school_credentials(account), token=account.callback_token, purpose=StkRequest.Purpose.FEES,
                  school=student.school, user=user, phone=phone, amount=_amount(amount),
                  reference=student_account(student), description="School fees", student=student)


def start_subscription_payment(invoice, user, phone):
    if not owner_ready():
        raise ValidationError({"detail": ["Paying by M-Pesa isn't available yet."]})
    if invoice.status != "open":
        raise ValidationError({"detail": ["This invoice isn't waiting for payment."]})
    if invoice.currency != "KES":
        raise ValidationError({"detail": ["This invoice isn't in shillings."]})
    return _start(creds=owner_credentials(), token=settings.MPESA_OWNER_CALLBACK_TOKEN,
                  purpose=StkRequest.Purpose.SUBSCRIPTION, school=invoice.school, user=user, phone=phone,
                  amount=_amount(invoice.amount.to_integral_value()), reference=school_account(invoice.school),
                  description="HouseMaster", invoice=invoice)


# Settling a payment ---------------------------------------------------------------

def _metadata(callback):
    items = ((callback.get("CallbackMetadata") or {}).get("Item")) or []
    return {i.get("Name"): i.get("Value") for i in items if isinstance(i, dict)}


def complete(stk, code, description, meta=None):
    """Record how a prompt went (once). A paid one becomes a fee payment or a paid invoice."""
    meta = meta or {}
    with transaction.atomic():
        stk = StkRequest.objects.select_for_update().get(pk=stk.pk)
        # A paid confirmation from M-Pesa (with its receipt) still counts after we'd stopped waiting.
        late_payment = stk.status == StkRequest.Status.FAILED and code == 0 and meta.get("MpesaReceiptNumber")
        if stk.status != StkRequest.Status.PENDING and not late_payment:
            return stk
        stk.result_description = str(description or "")[:255]
        stk.completed_at = timezone.now()
        if code != 0:
            stk.status = StkRequest.Status.FAILED
            stk.save(update_fields=["status", "result_description", "completed_at"])
            return stk
        paid = meta.get("Amount")
        if paid is not None and Decimal(str(paid)) != stk.amount:  # never trust a different amount
            stk.status = StkRequest.Status.FAILED
            stk.result_description = "The amount M-Pesa reported didn't match the request; the bursar will check it."
            stk.save(update_fields=["status", "result_description", "completed_at"])
            logger.warning("STK %s: amount %s differs from %s", stk.id, paid, stk.amount)
            return stk
        stk.status = StkRequest.Status.PAID
        stk.receipt = str(meta.get("MpesaReceiptNumber") or "")[:30]
        today = school_localdate(stk.school)
        if stk.purpose == StkRequest.Purpose.FEES:
            from fees.services import record_payment

            stk.fee_payment = record_payment(stk.student, None, Decimal(stk.amount), today, "mpesa", stk.receipt,
                                             stk.requested_by_name, by_name="M-Pesa")
        else:
            from billing.services import record_payment

            if stk.invoice.status == "open":
                record_payment(stk.invoice, today, "mpesa", stk.receipt)
        stk.save()
    return stk


def handle_stk_callback(token, body):
    callback = ((body or {}).get("Body") or {}).get("stkCallback") or {}
    checkout_id = callback.get("CheckoutRequestID")
    stk = StkRequest.objects.filter(checkout_request_id=checkout_id or "-").select_related("school").first()
    if stk is None or not _token_matches(stk, token):
        return None
    try:
        code = int(callback.get("ResultCode"))
    except (TypeError, ValueError):
        return None
    meta = _metadata(callback)
    if stk.status == StkRequest.Status.PAID and not stk.receipt and code == 0 and meta.get("MpesaReceiptNumber"):
        # Settled earlier by asking M-Pesa, which doesn't give the receipt: fill it in now.
        stk.receipt = str(meta["MpesaReceiptNumber"])[:30]
        stk.save(update_fields=["receipt"])
        if stk.fee_payment_id:
            type(stk.fee_payment).objects.filter(pk=stk.fee_payment_id).update(reference=stk.receipt)
        elif stk.invoice_id:
            type(stk.invoice).objects.filter(pk=stk.invoice_id).update(payment_reference=stk.receipt)
        return stk
    return complete(stk, code, callback.get("ResultDesc", ""), meta)


def _token_matches(stk, token):
    if stk.purpose == StkRequest.Purpose.SUBSCRIPTION:
        return bool(settings.MPESA_OWNER_CALLBACK_TOKEN) and token == settings.MPESA_OWNER_CALLBACK_TOKEN
    account = getattr(stk.school, "mpesa_account", None)
    return account is not None and token == account.callback_token


def refresh(stk):
    """While a prompt is waiting, ask M-Pesa now and then (a callback can be lost); give up after a few minutes."""
    if stk.status != StkRequest.Status.PENDING:
        return stk
    now = timezone.now()
    if now - stk.created_at < ASK_AGAIN_AFTER or (stk.checked_at and now - stk.checked_at < ASK_AGAIN_AFTER):
        return stk
    StkRequest.objects.filter(pk=stk.pk).update(checked_at=now)
    try:
        code, description = daraja.stk_query(credentials_for(stk), stk.checkout_request_id)
    except daraja.DarajaError:
        code, description = None, ""
    if code is None:
        if now - stk.created_at > GIVE_UP_AFTER:
            return complete(stk, 1037, "No answer from the phone. Please try again.")
        stk.refresh_from_db()
        return stk
    # A query can say it was paid but not give the receipt: the callback (or the bursar) fills it in.
    return complete(stk, code, description, {})


def stk_row(stk):
    return {"id": stk.id, "status": stk.status, "status_label": stk.get_status_display(), "amount": stk.amount,
            "phone": stk.phone_masked, "receipt": stk.receipt, "message": stk.result_description,
            "created_at": stk.created_at}


# Payments made straight to the paybill (C2B) ------------------------------------

def _paid_at(value):
    try:
        return datetime.strptime(str(value), "%Y%m%d%H%M%S").replace(tzinfo=daraja.NAIROBI)
    except ValueError:
        return timezone.now()


def handle_c2b(token, body):
    """Record a confirmed paybill payment (once per M-Pesa transaction). Returns the C2BPayment, or None."""
    body = body or {}
    trans_id = str(body.get("TransID") or "")[:30]
    try:
        amount = Decimal(str(body.get("TransAmount")))
    except Exception:
        return None
    if not trans_id or amount <= 0:
        return None
    owner = bool(settings.MPESA_OWNER_CALLBACK_TOKEN) and token == settings.MPESA_OWNER_CALLBACK_TOKEN
    account = None if owner else MpesaAccount.objects.filter(callback_token=token).select_related("school").first()
    if not owner and account is None:
        return None
    payer = " ".join(str(body.get(k) or "").strip() for k in ("FirstName", "MiddleName", "LastName")).strip()
    row = dict(trans_id=trans_id, amount=amount, bill_ref=str(body.get("BillRefNumber") or "")[:60], payer_name=payer[:150],
               phone_masked=mask(str(body.get("MSISDN") or ""))[:20], paid_at=_paid_at(body.get("TransTime")))
    try:
        with transaction.atomic():
            if owner:
                return _c2b_subscription(row)
            return _c2b_fees(account.school, row)
    except IntegrityError:  # M-Pesa sent the same transaction again
        return C2BPayment.objects.filter(trans_id=trans_id).first()


def _c2b_fees(school, row):
    from fees.services import record_payment

    student = find_student(school, row["bill_ref"])
    c2b = C2BPayment.objects.create(purpose=StkRequest.Purpose.FEES, school=school, student=student,
                                    status=C2BPayment.Status.RECORDED if student else C2BPayment.Status.UNMATCHED, **row)
    if student:
        c2b.fee_payment = record_payment(student, None, row["amount"], row["paid_at"].astimezone(daraja.NAIROBI).date(),
                                         "mpesa", row["trans_id"], row["payer_name"], by_name="M-Pesa")
        c2b.save(update_fields=["fee_payment"])
    return c2b


def assign(c2b, student, user):
    """The bursar says which student an unmatched paybill payment was for."""
    from fees.services import record_payment

    c2b.student = student
    c2b.status = C2BPayment.Status.RECORDED
    c2b.handled_by_name = display_name(user)
    c2b.fee_payment = record_payment(student, user, c2b.amount, c2b.paid_at.astimezone(daraja.NAIROBI).date(), "mpesa",
                                     c2b.trans_id, c2b.payer_name)
    c2b.save()
    return c2b


def _c2b_subscription(row):
    from billing.models import Invoice
    from billing.services import record_payment
    from students.models import School

    ref = _clean(row["bill_ref"])
    invoice = None
    if m := re.fullmatch(r"HM0*(\d+)", ref):
        school = School.objects.filter(pk=int(m.group(1))).first()
        invoice = (Invoice.objects.filter(school=school, status="open").order_by("due_on").first() if school else None)
    if invoice is None:
        invoice = next((i for i in Invoice.objects.filter(status="open") if _clean(i.number) == ref), None)
    c2b = C2BPayment.objects.create(purpose=StkRequest.Purpose.SUBSCRIPTION, school=invoice.school if invoice else None,
                                    invoice=invoice, status=C2BPayment.Status.UNMATCHED, **row)
    if invoice and row["amount"] >= invoice.amount:
        record_payment(invoice, row["paid_at"].astimezone(daraja.NAIROBI).date(), "mpesa", row["trans_id"])
        c2b.status = C2BPayment.Status.RECORDED
        c2b.save(update_fields=["status"])
    else:
        _tell_owner_unmatched(c2b)
    return c2b


def _tell_owner_unmatched(c2b):
    from guardians.notifications import send_after_commit

    if not settings.BILLING_OWNER_EMAIL:
        return
    send_after_commit([(
        f"M-Pesa payment to check: KES {c2b.amount:,.2f} ({c2b.trans_id})",
        f"A payment to the HouseMaster paybill couldn't be matched to an unpaid invoice in full.\n\n"
        f"Amount: KES {c2b.amount:,.2f}\nAccount entered: {c2b.bill_ref or '—'}\nFrom: {c2b.payer_name or '—'}\n"
        f"M-Pesa code: {c2b.trans_id}\n\nRecord it by hand in the admin (Billing > Invoices) if it's a school's payment.",
        settings.BILLING_OWNER_EMAIL,
    )])
