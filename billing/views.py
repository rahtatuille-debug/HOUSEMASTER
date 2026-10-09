from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import HasSchoolProfile
from accounts.scoping import is_admin
from activity.services import log_activity

from mpesa import services as mpesa_services

from . import services
from .models import Invoice, Plan


def _admin(request):
    if not is_admin(request.user):
        raise PermissionDenied("Only the school's admins can see billing.")
    return request.user.profile.school


def invoice_row(i):
    return {"id": i.id, "number": i.number, "plan_name": i.plan_name, "students": i.students, "amount": i.amount,
            "currency": i.currency, "period_start": i.period_start, "period_end": i.period_end, "issued_on": i.issued_on,
            "due_on": i.due_on, "status": i.status, "status_label": i.get_status_display(), "paid_on": i.paid_on,
            "payment_method": i.get_payment_method_display() if i.payment_method else "",
            "payment_reference": i.payment_reference, "school_reported_at": i.school_reported_at}


def plan_row(p):
    return {"name": p.name, "max_students": p.max_students, "monthly_price": p.monthly_price,
            "price_per_student": p.price_per_student, "currency": p.currency}


@api_view(["GET"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def billing(request):
    """The school's subscription: status, tier, how to pay and its invoices (admins only)."""
    school = _admin(request)
    count = services.active_students(school)
    plan = services.tier_for(count)
    sub = services.subscription_for(school)
    return Response({
        **services.status(school), "exempt": sub.exempt, "grace_days": sub.grace_days,
        "students": count, "paid_until": services.paid_until(school),
        "plan": {**plan_row(plan), "monthly_amount": plan.amount_for(count)} if plan else None,
        "tiers": [plan_row(p) for p in Plan.objects.filter(is_active=True)],
        "payment_instructions": settings.BILLING_PAYMENT_INSTRUCTIONS,
        "invoices": [invoice_row(i) for i in Invoice.objects.filter(school=school).exclude(status=Invoice.Status.VOID)],
        # Paying by M-Pesa: the PIN prompt, or the owner's paybill with this account number.
        "mpesa": {"paybill": settings.MPESA_SHORTCODE, "account": mpesa_services.school_account(school)}
        if mpesa_services.owner_ready() else None,
    })


def _invoice(request, invoice_id):
    school = _admin(request)
    invoice = Invoice.objects.filter(pk=invoice_id, school=school).exclude(status=Invoice.Status.VOID).first()
    if invoice is None:
        raise NotFound("Invoice not found.")
    return invoice


@api_view(["POST"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def report_payment(request, invoice_id):
    """POST {method, reference, note}: tell HouseMaster you've paid; it's checked and recorded by hand."""
    invoice = _invoice(request, invoice_id)
    if invoice.status != Invoice.Status.OPEN:
        raise ValidationError({"detail": ["This invoice isn't waiting for payment."]})
    method = str(request.data.get("method", ""))[:20]
    reference = str(request.data.get("reference", "")).strip()[:100]
    note = str(request.data.get("note", "")).strip()[:300]
    if not reference:
        raise ValidationError({"reference": ["Give the payment's reference (e.g. the M-Pesa code)."]})
    invoice.school_reported_at = timezone.now()
    invoice.school_report = f"{method}: {reference}" + (f" ({note})" if note else "")
    invoice.save(update_fields=["school_reported_at", "school_report"])
    services.tell_owner(invoice, method, reference, note)
    log_activity(school=invoice.school, actor=request.user, action="billing.payment_reported",
                 summary=f"Said invoice {invoice.number} was paid ({method}, {reference})")
    return Response(invoice_row(invoice))


@api_view(["GET"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def invoice_pdf(request, invoice_id):
    from .pdf import invoice_pdf as build

    invoice = _invoice(request, invoice_id)
    response = HttpResponse(build(invoice), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="housemaster-invoice-{invoice.number}.pdf"'
    return response


@api_view(["POST"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def billing_mpesa(request, invoice_id):
    """POST {phone}: send an M-Pesa PIN prompt for this invoice to the admin's phone."""
    invoice = _invoice(request, invoice_id)
    return Response(mpesa_services.stk_row(mpesa_services.start_subscription_payment(invoice, request.user,
                                                                                     request.data.get("phone"))), status=201)


@api_view(["GET"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def billing_mpesa_status(request, request_id):
    from mpesa.models import StkRequest

    school = _admin(request)
    stk = StkRequest.objects.filter(pk=request_id, school=school, purpose="subscription").first()
    if stk is None:
        raise NotFound("Not found.")
    return Response(mpesa_services.stk_row(mpesa_services.refresh(stk)))
