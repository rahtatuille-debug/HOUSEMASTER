from decimal import Decimal, InvalidOperation

from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import HasSchoolProfile
from accounts.scoping import can_manage_fees
from activity.services import display_name, log_activity, student_name
from gradebook.models import Term
from students.localtime import school_localdate
from students.models import Student

from . import services
from .models import METHODS, Charge, FeeItem, Payment, PaymentClaim

METHOD_KEYS = {k for k, _ in METHODS}


class ManagesFees(BasePermission):
    message = "Only the bursar and admins can manage fees."

    def has_permission(self, request, view):
        return hasattr(request.user, "profile") and can_manage_fees(request.user)


STAFF = [IsAuthenticated, HasSchoolProfile, ManagesFees]


def _school(request):
    return request.user.profile.school


def _amount(value, field="amount", allow_negative=False):
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError({field: ["Enter an amount, e.g. 15000."]})
    if (amount < 0 and not allow_negative) or amount == 0 or abs(amount) >= Decimal("10000000000"):
        raise ValidationError({field: ["Enter an amount more than 0."]})
    return amount


def _date(school, value, field="paid_on"):
    from datetime import date

    if not value:
        return school_localdate(school)
    try:
        day = date.fromisoformat(str(value))
    except ValueError:
        raise ValidationError({field: ["Use a date like 2026-10-07."]})
    if day > school_localdate(school):
        raise ValidationError({field: ["That date hasn't happened yet."]})
    return day


def _method(value):
    if value not in METHOD_KEYS:
        raise ValidationError({"method": ["Choose how it was paid."]})
    return value


# Rows ---------------------------------------------------------------------------

def charge_row(c):
    return {"id": c.id, "kind": c.kind, "kind_label": c.get_kind_display(), "description": c.description,
            "amount": c.amount, "term": c.term.name if c.term else "", "created_at": c.created_at,
            "created_by_name": c.created_by_name, "from_fee_item": c.item_id is not None}


def payment_row(p, staff=True):
    row = {"id": p.id, "amount": p.amount, "paid_on": p.paid_on, "method": p.method, "method_label": p.get_method_display(),
           "reference": p.reference, "payer_name": p.payer_name, "receipt_number": p.receipt_number,
           "voided": p.voided_at is not None}
    if staff:
        row.update({"recorded_by_name": p.recorded_by_name, "created_at": p.created_at, "voided_at": p.voided_at,
                    "void_reason": p.void_reason, "voided_by_name": p.voided_by_name})
    return row


def claim_row(c):
    return {"id": c.id, "student": c.student_id, "student_name": f"{c.student.first_name} {c.student.last_name}",
            "class_name": c.student.school_class.name if c.student.school_class_id else "",
            "claimed_by_name": c.claimed_by_name, "amount": c.amount, "paid_on": c.paid_on, "method": c.method,
            "method_label": c.get_method_display(), "reference": c.reference, "note": c.note, "status": c.status,
            "status_label": c.get_status_display(), "reject_reason": c.reject_reason, "created_at": c.created_at,
            "decided_by_name": c.decided_by_name, "receipt_number": c.payment.receipt_number if c.payment_id else ""}


def statement(student, staff=True):
    charged, paid = services.balances([student])[student.id]
    payments = Payment.objects.filter(student=student)
    if not staff:
        payments = payments.filter(voided_at__isnull=True)
    return {
        "student": student.id, "student_name": f"{student.first_name} {student.last_name}",
        "currency": services.settings_for(student.school).currency,
        "charged": charged, "paid": paid, "balance": charged - paid,
        "charges": [charge_row(c) for c in Charge.objects.filter(student=student).select_related("term")],
        "payments": [payment_row(p, staff) for p in payments],
        "claims": [claim_row(c) for c in PaymentClaim.objects.filter(student=student)
                   .select_related("student__school_class", "payment")[:20]],
    }


# Staff --------------------------------------------------------------------------

@api_view(["GET", "PATCH"])
@permission_classes(STAFF)
def fee_settings(request):
    """GET / PATCH {currency, payment_instructions}."""
    row = services.settings_for(_school(request))
    if request.method == "PATCH":
        if "currency" in request.data:
            currency = str(request.data["currency"]).strip().upper()
            if len(currency) != 3 or not currency.isalpha():
                raise ValidationError({"currency": ["Use a three-letter code, e.g. KES."]})
            row.currency = currency
        if "payment_instructions" in request.data:
            row.payment_instructions = str(request.data["payment_instructions"])[:1000]
        row.save()
        log_activity(school=row.school, actor=request.user, action="fees.settings", summary="Changed the fee settings")
    return Response({"currency": row.currency, "payment_instructions": row.payment_instructions})


class FeeItemSerializer(serializers.ModelSerializer):
    term_name = serializers.CharField(source="term.name", read_only=True)
    year_group_name = serializers.CharField(source="year_group.name", default="", read_only=True)
    applies_to_label = serializers.CharField(source="get_applies_to_display", read_only=True)
    billed = serializers.SerializerMethodField()

    class Meta:
        model = FeeItem
        fields = ["id", "term", "term_name", "name", "amount", "year_group", "year_group_name", "applies_to",
                  "applies_to_label", "billed"]

    def get_billed(self, obj):
        return obj.charges.count()

    def validate(self, attrs):
        school = self.context["school"]
        term = attrs.get("term", getattr(self.instance, "term", None))
        year = attrs.get("year_group", getattr(self.instance, "year_group", None))
        if term is not None and term.school_id != school.id:
            raise ValidationError({"term": ["Choose one of your school's terms."]})
        if year is not None and year.school_id != school.id:
            raise ValidationError({"year_group": ["Choose one of your school's year groups."]})
        if "amount" in attrs:
            attrs["amount"] = _amount(attrs["amount"])
        return attrs


class FeeItemViewSet(viewsets.ModelViewSet):
    """The fee items for a term (?term=). Changing an item doesn't change charges already billed."""

    serializer_class = FeeItemSerializer
    permission_classes = STAFF
    pagination_class = None

    def get_queryset(self):
        qs = FeeItem.objects.filter(school=_school(self.request)).select_related("term", "year_group")
        if term := self.request.query_params.get("term"):
            qs = qs.filter(term_id=term)
        return qs

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "school": _school(self.request)}

    def perform_create(self, serializer):
        item = serializer.save(school=_school(self.request))
        log_activity(school=item.school, actor=self.request.user, action="fees.item",
                     summary=f"Added the fee item {item.name} ({item.term.name})")

    def perform_destroy(self, instance):
        if instance.charges.exists():
            raise ValidationError({"detail": ["Students have already been billed for this. Change their charges instead."]})
        instance.delete()


@api_view(["POST"])
@permission_classes(STAFF)
def bill_term(request):
    """POST {term}: charge every active student the term's fee items they haven't been charged yet."""
    term = Term.objects.filter(school=_school(request), pk=request.data.get("term")).first()
    if term is None:
        raise ValidationError({"term": ["Choose a term."]})
    return Response({"created": services.bill_term(term, request.user)})


@api_view(["GET"])
@permission_classes(STAFF)
def student_balances(request):
    """GET ?school_class=&owing=1&search=: each active student's charges, payments and balance, with totals."""
    school = _school(request)
    students = Student.objects.filter(school=school, is_active=True).select_related("school_class")
    if school_class := request.query_params.get("school_class"):
        students = students.filter(school_class_id=school_class)
    if search := request.query_params.get("search", "").strip():
        for word in search.split()[:3]:
            students = students.filter(Q(first_name__icontains=word) | Q(last_name__icontains=word) |
                                       Q(external_id__icontains=word))
    students = list(students.order_by("school_class__name", "last_name", "first_name"))
    sums = services.balances(students)
    rows = []
    for s in students:
        charged, paid = sums[s.id]
        rows.append({"student": s.id, "name": f"{s.first_name} {s.last_name}", "external_id": s.external_id,
                     "class_name": s.school_class.name if s.school_class_id else "", "charged": charged, "paid": paid,
                     "balance": charged - paid})
    if request.query_params.get("owing"):
        rows = [r for r in rows if r["balance"] > 0]
    totals = {k: sum((r[k] for r in rows), Decimal("0")) for k in ("charged", "paid", "balance")}
    totals["owing"] = sum(1 for r in rows if r["balance"] > 0)
    return Response({"currency": services.settings_for(school).currency, "students": rows, "totals": totals,
                     "open_claims": PaymentClaim.objects.filter(school=school, status=PaymentClaim.Status.OPEN).count()})


def _student(request, student_id):
    return get_object_or_404(Student, pk=student_id, school=_school(request))


@api_view(["GET"])
@permission_classes(STAFF)
def student_statement(request, student_id):
    return Response(statement(_student(request, student_id)))


@api_view(["POST"])
@permission_classes(STAFF)
def add_charge(request, student_id):
    """POST {kind: extra|discount, description, amount (positive)}: a discount or bursary reduces the balance."""
    student = _student(request, student_id)
    kind = request.data.get("kind")
    if kind not in (Charge.Kind.EXTRA, Charge.Kind.DISCOUNT):
        raise ValidationError({"kind": ["Choose an extra charge or a discount."]})
    description = str(request.data.get("description", "")).strip()[:150]
    if not description:
        raise ValidationError({"description": ["Say what it's for."]})
    amount = _amount(request.data.get("amount"))
    charge = Charge.objects.create(school=student.school, student=student, kind=kind, description=description,
                                   amount=-amount if kind == Charge.Kind.DISCOUNT else amount,
                                   created_by_name=display_name(request.user))
    log_activity(school=student.school, actor=request.user, action="fees.charge", target=student,
                 summary=f"Added {charge.get_kind_display().lower()} '{description}' for {student_name(student)}")
    return Response(statement(student), status=201)


@api_view(["DELETE"])
@permission_classes(STAFF)
def remove_charge(request, charge_id):
    charge = get_object_or_404(Charge, pk=charge_id, school=_school(request))
    student = charge.student
    log_activity(school=student.school, actor=request.user, action="fees.charge_removed", target=student,
                 summary=f"Removed the charge '{charge.description}' for {student_name(student)}")
    charge.delete()
    return Response(statement(student))


@api_view(["POST"])
@permission_classes(STAFF)
def add_payment(request, student_id):
    """POST {amount, paid_on, method, reference, payer_name}: records it, numbers the receipt and emails the parents."""
    student = _student(request, student_id)
    services.record_payment(
        student, request.user, _amount(request.data.get("amount")), _date(student.school, request.data.get("paid_on")),
        _method(request.data.get("method")), str(request.data.get("reference", "")).strip(),
        str(request.data.get("payer_name", "")).strip())
    return Response(statement(student), status=201)


@api_view(["POST"])
@permission_classes(STAFF)
def void_payment(request, payment_id):
    """POST {reason}: the payment no longer counts; its receipt number isn't reused."""
    payment = get_object_or_404(Payment, pk=payment_id, school=_school(request), voided_at__isnull=True)
    reason = str(request.data.get("reason", "")).strip()
    if not reason:
        raise ValidationError({"reason": ["Say why, e.g. entered twice."]})
    services.void_payment(payment, request.user, reason)
    return Response(statement(payment.student))


@api_view(["GET"])
@permission_classes(STAFF)
def staff_receipt(request, payment_id):
    return _receipt_response(get_object_or_404(Payment, pk=payment_id, school=_school(request)))


@api_view(["GET"])
@permission_classes(STAFF)
def claims(request):
    """GET ?status=open (default) | all: what parents say they've paid."""
    qs = PaymentClaim.objects.filter(school=_school(request)).select_related("student__school_class", "payment")
    if request.query_params.get("status", "open") != "all":
        qs = qs.filter(status=PaymentClaim.Status.OPEN)
    return Response([claim_row(c) for c in qs[:300]])


def _open_claim(request, claim_id):
    return get_object_or_404(PaymentClaim, pk=claim_id, school=_school(request), status=PaymentClaim.Status.OPEN)


@api_view(["POST"])
@permission_classes(STAFF)
def confirm_claim(request, claim_id):
    """POST {amount?}: the money arrived; records the payment (the amount received, if different)."""
    claim = _open_claim(request, claim_id)
    amount = _amount(request.data["amount"]) if request.data.get("amount") not in (None, "") else claim.amount
    services.record_payment(claim.student, request.user, amount, claim.paid_on, claim.method, claim.reference,
                            claim.claimed_by_name, claim=claim)
    claim.refresh_from_db()
    return Response(claim_row(claim))


@api_view(["POST"])
@permission_classes(STAFF)
def reject_claim(request, claim_id):
    """POST {reason}: the payment can't be found; the parent sees the reason."""
    claim = _open_claim(request, claim_id)
    reason = str(request.data.get("reason", "")).strip()[:200]
    if not reason:
        raise ValidationError({"reason": ["Tell the parent why, e.g. no payment with that code."]})
    claim.status = PaymentClaim.Status.REJECTED
    claim.reject_reason = reason
    claim.decided_by_name = display_name(request.user)
    claim.decided_at = timezone.now()
    claim.save(update_fields=["status", "reject_reason", "decided_by_name", "decided_at"])
    log_activity(school=claim.school, actor=request.user, action="fees.claim_rejected", target=claim.student,
                 summary=f"Couldn't find the payment a parent reported for {student_name(claim.student)}")
    return Response(claim_row(claim))


@api_view(["POST"])
@permission_classes(STAFF)
def remind(request):
    """POST {school_class?}: email the parents of every student who owes (in the class, or the school)."""
    students = Student.objects.filter(school=_school(request), is_active=True)
    if school_class := request.data.get("school_class"):
        students = students.filter(school_class_id=school_class)
    return Response({"emailed": services.email_balances(students, request.user)})


# Parents (called from guardians.views.GuardianStudentViewSet) -------------------

def guardian_fees(student):
    fee = services.settings_for(student.school)
    from mpesa.views import guardian_mpesa_info

    return {**statement(student, staff=False), "payment_instructions": fee.payment_instructions,
            "mpesa": guardian_mpesa_info(student) if fee.currency == "KES" else None}


def guardian_claim(request, student):
    """A parent says they've paid: {amount, paid_on, method, reference, note}."""
    if PaymentClaim.objects.filter(student=student, status=PaymentClaim.Status.OPEN).count() >= 5:
        raise ValidationError({"detail": ["The school is still checking your earlier payments."]})
    reference = str(request.data.get("reference", "")).strip()[:100]
    if not reference:
        raise ValidationError({"reference": ["Give the payment's reference, e.g. the M-Pesa code."]})
    claim = PaymentClaim.objects.create(
        school=student.school, student=student, claimed_by=request.user, claimed_by_name=request.user.guardian.name,
        amount=_amount(request.data.get("amount")), paid_on=_date(student.school, request.data.get("paid_on")),
        method=_method(request.data.get("method")), reference=reference,
        note=str(request.data.get("note", "")).strip()[:300])
    services.tell_bursars(claim)
    log_activity(school=student.school, actor=request.user, action="fees.claim", target=student,
                 summary=f"A parent said they paid fees for {student_name(student)}")
    return guardian_fees(student)


def guardian_receipt(student, payment_id):
    payment = Payment.objects.filter(student=student, pk=payment_id, voided_at__isnull=True).first()
    if payment is None:
        raise NotFound("Receipt not found.")
    return _receipt_response(payment)


def _receipt_response(payment):
    from .pdf import receipt_pdf

    response = HttpResponse(receipt_pdf(payment), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="receipt-{payment.receipt_number}.pdf"'
    return response
