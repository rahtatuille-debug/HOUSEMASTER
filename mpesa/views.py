from django.core.exceptions import RequestDataTooBig
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.exceptions import NotFound, ParseError, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from accounts.scoping import is_admin
from activity.services import display_name, log_activity
from fees.views import STAFF, _school
from students.models import Student

from . import daraja, services
from .models import C2BPayment, MpesaAccount, StkRequest
from .secrets_box import NoEncryptionKey, seal

ACCEPTED = {"ResultCode": 0, "ResultDesc": "Accepted"}


class CallbackThrottle(AnonRateThrottle):
    scope = "mpesa_callback"


def _settle(handler, what, request, token):
    try:
        handler(token, request.data)
    except (ParseError, RequestDataTooBig):  # not JSON, or far too big: noise, not a fault worth an error report
        services.logger.warning("M-Pesa %s: a body that isn't JSON, or is too big, was ignored", what)
    except Exception:  # never make M-Pesa retry forever on our mistake; it's logged
        services.logger.exception("M-Pesa %s failed", what)
    return Response(ACCEPTED)


# Safaricom calls these (no sign-in; the token in the address is the secret) --------

@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([CallbackThrottle])
def stk_hook(request, token):
    return _settle(services.handle_stk_callback, "STK callback", request, token)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([CallbackThrottle])
def c2b_confirm(request, token):
    return _settle(services.handle_c2b, "C2B confirmation", request, token)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([CallbackThrottle])
def c2b_validate(request, token):
    return Response(ACCEPTED)


# The school's own M-Pesa (the bursar and admins) -----------------------------------

def account_row(account, school, user=None):
    from fees.services import settings_for

    ready = bool(account and account.consumer_key and account.consumer_secret and account.passkey and account.shortcode)
    row = {"connected": ready, "enabled": bool(account and account.enabled), "kind": account.kind if account else "paybill",
           "shortcode": account.shortcode if account else "", "till_number": account.till_number if account else "",
           "environment": account.environment if account else "sandbox",
           "keys_saved": bool(account and account.consumer_key), "c2b_registered_at": account.c2b_registered_at if account else None,
           "currency_ok": settings_for(school).currency == "KES", "server_ready": True,
           "token_changed_at": account.token_changed_at if account else None,
           # Only admins change where the money goes (PAY-006); bursars see the settings.
           "can_change": bool(user and is_admin(user))}
    try:
        services.callback_base()
    except ValidationError:
        row["server_ready"] = False
    return row


def _admins_only(request, what):
    # Where the school's money goes is decided by an admin, never by one bursar alone (PAY-006).
    if not is_admin(request.user):
        raise PermissionDenied(f"Only the school's admins can {what}.")


def _describe(account):
    if account is None:
        return "not set up"
    number = f"till {account.till_number} (store {account.shortcode})" if account.kind == "till" else \
        f"paybill {account.shortcode}"
    return f"{number}, {account.get_environment_display().lower()}, {'on' if account.enabled else 'off'}"


def _tell_admins(school, actor, subject, lines):
    """Every admin hears about a change to where the school's money goes, including the one who made it."""
    from django.conf import settings

    from accounts.models import Profile
    from guardians.notifications import send_after_commit

    admins = Profile.objects.filter(school=school, role=Profile.Role.ADMIN, user__is_active=True) \
        .exclude(user__email="").select_related("user")
    body = (f"{display_name(actor)} changed {school.name}'s M-Pesa settings in HouseMaster.\n\n" + "\n".join(lines)
            + "\n\nIf you didn't expect this, check Fees > M-Pesa now and change it back: parents' payments go to "
              f"the number shown there.\n\n{settings.FRONTEND_URL}")
    send_after_commit([(subject, body, p.user.email) for p in admins])


@api_view(["GET", "PUT"])
@permission_classes(STAFF)
def fee_mpesa_settings(request):
    """GET / PUT {kind, shortcode, till_number, environment, enabled, consumer_key?, consumer_secret?, passkey?}.
    The keys are write-only: leave them out to keep the saved ones. Bursars can see; only admins can change."""
    school = _school(request)
    account = MpesaAccount.objects.filter(school=school).first()
    if request.method == "PUT":
        _admins_only(request, "change where M-Pesa payments go")
        before = _describe(account)
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
        keys_changed = []
        try:
            for field in ("consumer_key", "consumer_secret", "passkey"):
                value = str(data.get(field) or "").strip()
                if value:
                    setattr(account, field, seal(value))
                    keys_changed.append(field.replace("_", " "))
        except NoEncryptionKey:
            raise ValidationError({"detail": ["The server isn't set up to store M-Pesa keys safely yet "
                                              "(MPESA_ENCRYPTION_KEY). Ask HouseMaster's support."]})
        if not (account.consumer_key and account.consumer_secret and account.passkey):
            raise ValidationError({"consumer_key": ["Enter the consumer key, consumer secret and passkey from Daraja."]})
        account.save()
        after = _describe(account)
        lines = [f"Before: {before}", f"Now: {after}"] + ([f"New Daraja {', '.join(keys_changed)}"] if keys_changed else [])
        log_activity(school=school, actor=request.user, action="mpesa.settings",
                     summary=f"Changed M-Pesa from {before} to {after}"
                             + (f"; new {', '.join(keys_changed)}" if keys_changed else ""))
        if before != after or keys_changed:
            _tell_admins(school, request.user, f"{school.name}: M-Pesa settings changed", lines)
    return Response(account_row(account, school, request.user))


@api_view(["POST"])
@permission_classes(STAFF)
def fee_mpesa_connect(request):
    """Check the keys with M-Pesa and register where paybill payments are confirmed."""
    school = _school(request)
    account = MpesaAccount.objects.filter(school=school).first()
    if account is None:
        raise ValidationError({"detail": ["Save the M-Pesa details first."]})
    creds = services.school_credentials(account)
    urls = services.hook_urls(account.callback_token)
    try:
        daraja.register_c2b(creds, confirmation_url=urls["confirmation"], validation_url=urls["validation"])
    except daraja.DarajaError as err:
        raise ValidationError({"detail": [str(err)]})
    account.c2b_registered_at = timezone.now()
    account.save(update_fields=["c2b_registered_at"])
    log_activity(school=school, actor=request.user, action="mpesa.connected", summary="Connected M-Pesa to HouseMaster")
    return Response(account_row(account, school, request.user))


@api_view(["POST"])
@permission_classes(STAFF)
def fee_mpesa_new_address(request):
    """
    A new secret in the addresses M-Pesa calls (if the old one may have leaked). The paybill confirmation address
    is registered with M-Pesa again; if M-Pesa refuses, nothing changes. Prompts sent before keep settling: the
    sweeper and the parent's screen ask M-Pesa directly.
    """
    _admins_only(request, "change the M-Pesa callback address")
    school = _school(request)
    account = MpesaAccount.objects.filter(school=school).first()
    if account is None:
        raise ValidationError({"detail": ["Save the M-Pesa details first."]})
    creds = services.school_credentials(account)
    old = (account.token_hash, account.token_sealed, account.token_changed_at)
    try:
        token = account.set_callback_token()
    except NoEncryptionKey:
        raise ValidationError({"detail": ["The server isn't set up to store M-Pesa secrets safely yet "
                                          "(MPESA_ENCRYPTION_KEY). Ask HouseMaster's support."]})
    if account.c2b_registered_at:
        urls = services.hook_urls(token)
        try:
            daraja.register_c2b(creds, confirmation_url=urls["confirmation"], validation_url=urls["validation"])
        except daraja.DarajaError as err:
            account.token_hash, account.token_sealed, account.token_changed_at = old
            raise ValidationError({"detail": [f"M-Pesa didn't accept the new address, so nothing changed: {err} "
                                              "(Live paybills may need Safaricom to allow a new address.)"]})
        account.c2b_registered_at = timezone.now()
    account.save()
    log_activity(school=school, actor=request.user, action="mpesa.new_address",
                 summary="Changed the secret address M-Pesa calls")
    _tell_admins(school, request.user, f"{school.name}: M-Pesa callback address changed",
                 ["The secret address M-Pesa uses to tell HouseMaster about payments was changed. The old one no "
                  "longer works."])
    return Response(account_row(account, school, request.user))


def c2b_row(c):
    return {"id": c.id, "trans_id": c.trans_id, "amount": c.amount, "bill_ref": c.bill_ref, "payer_name": c.payer_name,
            "phone": c.phone_masked, "paid_at": c.paid_at, "status": c.status, "status_label": c.get_status_display(),
            "student": c.student_id, "student_name": f"{c.student.first_name} {c.student.last_name}" if c.student_id else "",
            "receipt_number": c.fee_payment.receipt_number if c.fee_payment_id else "", "handled_by_name": c.handled_by_name}


@api_view(["GET"])
@permission_classes(STAFF)
def fee_mpesa_payments(request):
    """GET ?status=unmatched|all: payments made straight to the school's paybill. Also settles lost prompts."""
    services.sweep_soon(_school(request))
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
