"""
The staff sign-up link: one link for every new member of staff.

An admin turns the link on in Staff and shares it (e.g. in the staff WhatsApp group). Whoever opens it gives their
name, email, and optionally a phone number and a note ("I teach Year 8 Maths"). That makes a request, not an
account: anyone could get hold of a shared link, so an admin approves each request. Approving emails that person
the usual staff invite, and they choose their password from it, which also proves the email is theirs. They join
as a teacher; an admin can change their role and classes afterwards in Staff.

The public page never says whether an email already has an account.
"""
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from activity.services import log_activity
from guardians.signup import MAX_PENDING, SignupThrottle

from .emails import send_staff_invite_email
from .models import Invite, Profile, StaffJoinLink, StaffSignupRequest
from .permissions import HasSchoolProfile, IsSchoolAdmin
from .throttles import InviteIPThrottle


class StaffSignupThrottle(SignupThrottle):
    scope = "staff_signup"


def _link(token):
    link = StaffJoinLink.objects.select_related("school").filter(token=token).first()
    if link is None or not link.is_active:
        raise NotFound("This sign-up link isn't working any more. Ask the school for a new one.")
    return link


class StaffJoinSerializer(serializers.Serializer):
    name = serializers.CharField(min_length=2, max_length=255)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    accept_privacy = serializers.BooleanField()

    def validate_accept_privacy(self, value):
        if not value:
            raise serializers.ValidationError("Please read and accept the privacy notice to continue.")
        return value

    def validate_name(self, value):
        return " ".join(value.split())

    def validate_phone(self, value):
        from guardians.serializers import _clean_phone

        return _clean_phone(value)

    def validate_note(self, value):
        return " ".join(value.split())


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
@throttle_classes([InviteIPThrottle, StaffSignupThrottle])
def staff_join(request, token):
    """Public. GET: the school the link is for. POST: ask to join as staff."""
    from students.presets import country

    link = _link(token)
    school = link.school
    if request.method == "GET":
        return Response({"school_name": school.name, "privacy_contact": school.privacy_contact,
                         "country": country(school.country)})

    data = StaffJoinSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    v = data.validated_data
    pending = StaffSignupRequest.objects.filter(school=school, status=StaffSignupRequest.Status.PENDING)
    # Asking again (e.g. with a corrected name) updates the earlier request.
    existing = pending.filter(email__iexact=v["email"]).first()
    if existing is None and pending.count() >= MAX_PENDING:
        raise ValidationError("The school has too many sign-ups waiting. Please try again later.")
    fields = {"name": v["name"], "phone": v["phone"], "note": v["note"]}
    if existing:
        for key, value in fields.items():
            setattr(existing, key, value)
        existing.save()
    else:
        StaffSignupRequest.objects.create(school=school, email=v["email"], **fields)
    return Response({"detail": f"Thank you. An admin at {school.name} will check your details and email you at "
                               f"{v['email']} with a link to choose your password."}, status=201)


def _row(r, staff_emails):
    return {"id": r.id, "name": r.name, "email": r.email, "phone": r.phone, "note": r.note, "status": r.status,
            "created_at": r.created_at, "has_account": r.email.lower() in staff_emails}


def _requests(school, status="pending"):
    rows = list(StaffSignupRequest.objects.filter(school=school, status=status)[:500])
    emails = {r.email.lower() for r in rows}
    taken = {e.lower() for e in User.objects.filter(email__in=[r.email for r in rows]).values_list("email", flat=True)}
    return [_row(r, taken & emails) for r in rows]


def _link_state(school):
    link = StaffJoinLink.objects.filter(school=school).first()
    return {"token": link.token if link and link.is_active else None,
            "waiting": StaffSignupRequest.objects.filter(school=school, status="pending").count()}


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, HasSchoolProfile, IsSchoolAdmin])
def staff_join_link(request):
    """GET: the school's staff sign-up link (token or null) and how many are waiting.
    POST {action: "create" | "renew" | "off"}: turn it on, replace it (the old one stops working), or turn it off."""
    school = request.user.profile.school
    if request.method == "POST":
        action = request.data.get("action")
        link = StaffJoinLink.objects.filter(school=school).first()
        if action == "create":
            if link is None:
                StaffJoinLink.objects.create(school=school, created_by=request.user)
            elif not link.is_active:
                link.is_active = True
                link.save(update_fields=["is_active"])
            summary = "Turned on the staff sign-up link"
        elif action == "renew" and link:
            link.renew()
            summary = "Replaced the staff sign-up link; the old link no longer works"
        elif action == "off" and link:
            link.is_active = False
            link.save(update_fields=["is_active"])
            summary = "Turned off the staff sign-up link"
        else:
            raise ValidationError({"action": "Choose create, renew or off."})
        log_activity(school=school, actor=request.user, action=f"staff_join_link.{action}", summary=summary)
    return Response(_link_state(school))


def approve(signup, admin):
    """Email the person a staff invite (as a teacher). Returns a sentence for the admin."""
    school = signup.school
    if User.objects.filter(email__iexact=signup.email).exists():
        raise ValidationError(f"{signup.email} already has a HouseMaster account, so it can't be used for a new one.")
    invite = Invite.objects.filter(school=school, email__iexact=signup.email, accepted_at__isnull=True).first()
    if invite:
        invite.name = invite.name or signup.name
        invite.phone = invite.phone or signup.phone
        invite.save(update_fields=["name", "phone"])
        invite.renew()
    else:
        invite = Invite.objects.create(school=school, name=signup.name, email=signup.email, phone=signup.phone,
                                       role=Profile.Role.TEACHER, invited_by=admin)
    send_staff_invite_email(invite, admin.profile.name)
    signup.status = StaffSignupRequest.Status.APPROVED
    signup.decided_by, signup.decided_at = admin, timezone.now()
    signup.save(update_fields=["status", "decided_by", "decided_at"])
    log_activity(school=school, actor=admin, action="staff_signup.approved", target=invite,
                 summary=f"Approved {signup.name} ({signup.email}) to join as staff and emailed them an invite",
                 email=signup.email)
    return f"Emailed {signup.name} a link to choose their password."


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, HasSchoolProfile, IsSchoolAdmin])
def staff_signup_requests(request):
    """GET ?status=pending|approved|rejected. POST {ids, decision: "approve" | "reject"}: decide one or many."""
    school = request.user.profile.school
    if request.method == "GET":
        status = request.query_params.get("status", "pending")
        if status not in StaffSignupRequest.Status.values:
            raise ValidationError({"status": "Unknown status."})
        return Response(_requests(school, status))

    ids = request.data.get("ids")
    decision = request.data.get("decision")
    if not isinstance(ids, list) or not ids or decision not in ("approve", "reject"):
        raise ValidationError("Send the request ids and a decision (approve or reject).")
    signups = list(StaffSignupRequest.objects.filter(school=school, status="pending", id__in=ids).select_related("school"))
    done, problems = [], []
    for signup in signups:
        if decision == "reject":
            signup.status = StaffSignupRequest.Status.REJECTED
            signup.decided_by, signup.decided_at = request.user, timezone.now()
            signup.save(update_fields=["status", "decided_by", "decided_at"])
            log_activity(school=school, actor=request.user, action="staff_signup.rejected",
                         summary=f"Turned down the staff sign-up from {signup.name} ({signup.email})", email=signup.email)
            done.append(f"Turned down {signup.name}.")
            continue
        try:
            with transaction.atomic():
                done.append(approve(signup, request.user))
        except ValidationError as exc:
            problems.append(f"{signup.name}: {' '.join(str(d) for d in exc.detail)}")
    return Response({"done": done, "problems": problems, "requests": _requests(school)})
