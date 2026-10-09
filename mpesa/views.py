from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from activity.services import display_name, log_activity
from fees.views import STAFF, _school
from students.models import Student

from . import daraja, services
from .models import C2BPayment, MpesaAccount, StkRequest
from .secrets_box import seal

ACCEPTED = {"ResultCode": 0, "ResultDesc": "Accepted"}


# Safaricom calls these (no sign-in; the token in the address is the secret) --------

@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def stk_hook(request, token):
    try:
        services.handle_stk_callback(token, request.data)
    except Exception:  # never make M-Pesa retry forever on our mistake; it's logged
        services.logger.exception("M-Pesa STK callback failed")
    return Response(ACCEPTED)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def c2b_confirm(request, token):
    try:
        services.handle_c2b(token, request.data)
    except Exception:
        services.logger.exception("M-Pesa C2B confirmation failed")
    return Response(ACCEPTED)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def c2b_validate(request, token):
    return Response(ACCEPTED)


# The school's own M-Pesa (the bursar and admins) -----------------------------------

def account_row(account, school):
    from fees.services import settings_for

    ready = bool(account and account.consumer_key and account.consumer_secret and account.passkey and account.shortcode)
    row = {"connected": ready, "enabled": bool(account and account.enabled), "kind": account.kind if account else "paybill",
           "shortcode": account.shortcode if account else "", "till_number": account.till_number if account else "",
           "environment": account.environment if account else "sandbox",
           "keys_saved": bool(account and account.consumer_key), "c2b_registered_at": account.c2b_registered_at if account else None,
           "currency_ok": settings_for(school).currency == "KES", "server_ready": True}
    try:
        services.callback_base()
    except ValidationError:
        row["server_ready"] = False
    return row


@api_view(["GET", "PUT"])
@permission_classes(STAFF)
def fee_mpesa_settings(request):
    """GET / PUT {kind, shortcode, till_number, environment, enabled, consumer_key?, consumer_secret?, passkey?}.
    The keys are write-only: leave them out to keep the saved ones."""
    school = _school(request)
    account = MpesaAccount.objects.filter(school=school).first()
    if request.method == "PUT":
        data = request.data
        kind = data.get("kind", "paybill")
        if kind not in MpesaAccount.Kind.values:
            raise ValidationError({"kind": ["Paybill or till."]})
        shortcode = str(data.get("shortcode", "")).strip()
        till = str(data.get("till_number", "")).strip()
        if not shortcode.isdigit() or not 5 <= len(shortcode) <= 7:
            raise ValidationError({"shortcode": ["Enter the paybill number (or, for a till, the store number), digits only."]})
        if kind == "till" and (not till.isdigit() or not 5 <= len(till) <= 8):
            raise ValidationError({"till_number": ["Enter the till number, digits only."]})
        environment = data.get("environment", "sandbox")
        if environment not in MpesaAccount.Environment.values:
            raise ValidationError({"environment": ["Sandbox or live."]})
        account = account or MpesaAccount(school=school)
        account.kind, account.shortcode, account.till_number = kind, shortcode, till if kind == "till" else ""
        account.environment = environment
        account.enabled = bool(data.get("enabled", True))
        for field in ("consumer_key", "consumer_secret", "passkey"):
            value = str(data.get(field) or "").strip()
            if value:
                setattr(account, field, seal(value))
        if not (account.consumer_key and account.consumer_secret and account.passkey):
            raise ValidationError({"consumer_key": ["Enter the consumer key, consumer secret and passkey from Daraja."]})
        account.save()
        log_activity(school=school, actor=request.user, action="mpesa.settings",
                     summary=f"Saved the school's M-Pesa {account.get_kind_display().lower()} {shortcode}")
    return Response(account_row(account, school))


@api_view(["POST"])
@permission_classes(STAFF)
def fee_mpesa_connect(request):
    """Check the keys with M-Pesa and register where paybill payments are confirmed."""
    school = _school(request)
    account = MpesaAccount.objects.filter(school=school).first()
    if account is None:
        raise ValidationError({"detail": ["Save the M-Pesa details first."]})
    urls = services.hook_urls(account.callback_token)
    try:
        daraja.register_c2b(services.school_credentials(account), confirmation_url=urls["confirmation"],
                            validation_url=urls["validation"])
    except daraja.DarajaError as err:
        raise ValidationError({"detail": [str(err)]})
    account.c2b_registered_at = timezone.now()
    account.save(update_fields=["c2b_registered_at"])
    log_activity(school=school, actor=request.user, action="mpesa.connected", summary="Connected M-Pesa to HouseMaster")
    return Response(account_row(account, school))


def c2b_row(c):
    return {"id": c.id, "trans_id": c.trans_id, "amount": c.amount, "bill_ref": c.bill_ref, "payer_name": c.payer_name,
            "phone": c.phone_masked, "paid_at": c.paid_at, "status": c.status, "status_label": c.get_status_display(),
            "student": c.student_id, "student_name": f"{c.student.first_name} {c.student.last_name}" if c.student_id else "",
            "receipt_number": c.fee_payment.receipt_number if c.fee_payment_id else "", "handled_by_name": c.handled_by_name}


@api_view(["GET"])
@permission_classes(STAFF)
def fee_mpesa_payments(request):
    """GET ?status=unmatched|all: payments made straight to the school's paybill."""
    qs = C2BPayment.objects.filter(school=_school(request), purpose="fees").select_related("student", "fee_payment")
    if request.query_params.get("status", "unmatched") != "all":
        qs = qs.filter(status=C2BPayment.Status.UNMATCHED)
    return Response([c2b_row(c) for c in qs[:300]])


def _unmatched(request, payment_id):
    return get_object_or_404(C2BPayment, pk=payment_id, school=_school(request), purpose="fees",
                             status=C2BPayment.Status.UNMATCHED)


@api_view(["POST"])
@permission_classes(STAFF)
def fee_mpesa_assign(request, payment_id):
    """POST {student}: record an unmatched paybill payment for this student (receipt emailed)."""
    c2b = _unmatched(request, payment_id)
    student = Student.objects.filter(school=c2b.school, pk=request.data.get("student")).first()
    if student is None:
        raise ValidationError({"student": ["Choose a student."]})
    return Response(c2b_row(services.assign(c2b, student, request.user)))


@api_view(["POST"])
@permission_classes(STAFF)
def fee_mpesa_ignore(request, payment_id):
    """Not a fees payment (e.g. for the canteen): it stays listed under All, not to do."""
    c2b = _unmatched(request, payment_id)
    c2b.status = C2BPayment.Status.IGNORED
    c2b.handled_by_name = display_name(request.user)
    c2b.save(update_fields=["status", "handled_by_name"])
    return Response(c2b_row(c2b))


# Parents (called from guardians.views) and admins paying their subscription --------

def guardian_pay(request, student):
    """POST {phone, amount}: send the PIN prompt to the parent's phone."""
    stk = services.start_fee_payment(student, request.user, request.data.get("phone"), request.data.get("amount"))
    return services.stk_row(stk)


def guardian_pay_status(request, student, request_id):
    stk = StkRequest.objects.filter(pk=request_id, student=student, requested_by=request.user).first()
    if stk is None:
        raise NotFound("Not found.")
    return services.stk_row(services.refresh(stk))


def guardian_mpesa_info(student):
    account = services.school_ready(student.school)
    if account is None:
        return None
    return {"kind": account.kind, "number": account.till_number if account.kind == "till" else account.shortcode,
            "account": services.student_account(student)}
