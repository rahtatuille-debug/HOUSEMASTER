"""
Class sign-up links: the quick way to bring in a whole class of parents.

An admin turns on a link for a class and shares it (e.g. in the class
WhatsApp group). A parent who opens it gives their name, email, phone,
relationship and their child's admission number. That makes a request, not
an account: an admission number alone doesn't prove who someone is, so an
admin approves each request, seeing which child it matched and who that
child's parents already are. Approving emails the parent their own invite
link (which also proves the email is theirs), or, if they already have a
parent account at the school, adds the child to it.

The public page never says whether an admission number matched, so the link
can't be used to find out which students exist.
"""
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

from accounts.permissions import HasSchoolProfile, IsSchoolAdmin
from activity.services import log_activity, student_name
from students.models import SchoolClass, Student

from .invite_emails import send_child_added_email, send_invite_email
from .models import ClassSignupLink, Guardian, GuardianInvite, ParentSignupRequest

# A school can't be flooded with more waiting requests than this.
MAX_PENDING = 2000


class SignupThrottle(SimpleRateThrottle):
    """Limits sign-up requests per IP address."""
    scope = "parent_signup"
    rate = "20/hour"

    def get_cache_key(self, request, view):
        if request.method != "POST":
            return None
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


def _link(token):
    try:
        link = ClassSignupLink.objects.select_related("school", "school_class__year_group").get(token=token)
    except ClassSignupLink.DoesNotExist:
        link = None
    if link is None or not link.is_active:
        raise NotFound("This sign-up link isn't working any more. Ask the school for a new one.")
    return link


class JoinSerializer(serializers.Serializer):
    name = serializers.CharField(min_length=2, max_length=255)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    relationship = serializers.ChoiceField(choices=Guardian.Relationship.choices, required=False, allow_blank=True,
                                           default="")
    admission_number = serializers.CharField(max_length=50)
    accept_privacy = serializers.BooleanField()

    def validate_accept_privacy(self, value):
        if not value:
            raise serializers.ValidationError("Please read and accept the privacy notice to continue.")
        return value

    def validate_name(self, value):
        return " ".join(value.split())

    def validate_admission_number(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Enter your child's admission number.")
        return value


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
@throttle_classes([SignupThrottle])
def join(request, token):
    """
    Public. GET: the school and class the link is for. POST: ask to join as
    a parent. The answer is the same whether or not the admission number
    matched a student.
    """
    from students.presets import country

    link = _link(token)
    school = link.school
    if request.method == "GET":
        return Response({
            "school_name": school.name, "class_name": link.school_class.name,
            "year_group": link.school_class.year_group.name, "privacy_contact": school.privacy_contact,
            "country": country(school.country),
        })

    data = JoinSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    v = data.validated_data
    student = Student.objects.filter(school=school, external_id__iexact=v["admission_number"], is_active=True).first()
    pending = ParentSignupRequest.objects.filter(school=school, status=ParentSignupRequest.Status.PENDING)
    # Asking again (e.g. with a corrected phone number) updates the earlier request.
    existing = pending.filter(email__iexact=v["email"], admission_number__iexact=v["admission_number"]).first()
    if existing is None and pending.count() >= MAX_PENDING:
        raise ValidationError("The school has too many sign-ups waiting. Please try again later.")
    fields = {"name": v["name"], "phone": v["phone"].strip(), "relationship": v["relationship"],
              "school_class": link.school_class, "student": student}
    if existing:
        for key, value in fields.items():
            setattr(existing, key, value)
        existing.save()
    else:
        ParentSignupRequest.objects.create(school=school, email=v["email"], admission_number=v["admission_number"],
                                           **fields)
    return Response({"detail": f"Thank you. {school.name} will check your details and email you at "
                               f"{v['email']} with a link to finish setting up your account."}, status=201)


def _class(request, value):
    try:
        return SchoolClass.objects.select_related("year_group").get(
            pk=value, year_group__school=request.user.profile.school)
    except (SchoolClass.DoesNotExist, ValueError, TypeError):
        raise NotFound("Class not found.")


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, HasSchoolProfile, IsSchoolAdmin])
def signup_links(request):
    """
    GET: every class with its sign-up link (if any) and how many requests
    are waiting. POST {school_class, action: "create" | "renew" | "off"}:
    turn a class's link on, replace it with a new one, or turn it off.
    """
    school = request.user.profile.school
    if request.method == "POST":
        klass = _class(request, request.data.get("school_class"))
        action = request.data.get("action")
        link = ClassSignupLink.objects.filter(school_class=klass).first()
        if action == "create":
            if link is None:
                link = ClassSignupLink.objects.create(school=school, school_class=klass, created_by=request.user)
            elif not link.is_active:
                link.is_active = True
                link.save(update_fields=["is_active"])
            summary = f"Turned on the parent sign-up link for {klass.name}"
        elif action == "renew" and link:
            link.renew()
            summary = f"Replaced the parent sign-up link for {klass.name}; the old link no longer works"
        elif action == "off" and link:
            link.is_active = False
            link.save(update_fields=["is_active"])
            summary = f"Turned off the parent sign-up link for {klass.name}"
        else:
            raise ValidationError({"action": "Choose create, renew or off."})
        log_activity(school=school, actor=request.user, action=f"signup_link.{action}", target=klass, summary=summary)

    links = {link.school_class_id: link for link in ClassSignupLink.objects.filter(school=school)}
    waiting = {}
    for class_id in ParentSignupRequest.objects.filter(school=school, status="pending") \
            .values_list("school_class_id", flat=True):
        waiting[class_id] = waiting.get(class_id, 0) + 1
    classes = SchoolClass.objects.filter(year_group__school=school).select_related("year_group") \
        .order_by("year_group__order", "year_group__name", "name")
    return Response([{
        "school_class": c.id, "class_name": c.name, "year_group": c.year_group.name,
        "token": links[c.id].token if c.id in links and links[c.id].is_active else None,
        "waiting": waiting.get(c.id, 0),
    } for c in classes])


def _row(r, parents_by_student, parent_emails):
    student = r.student
    return {
        "id": r.id, "name": r.name, "email": r.email, "phone": r.phone, "relationship": r.relationship,
        "admission_number": r.admission_number, "class_name": r.school_class.name, "status": r.status,
        "created_at": r.created_at,
        "student": {"id": student.id, "name": student_name(student), "admission_number": student.external_id,
                    "class_name": student.school_class.name if student.school_class else "",
                    "in_this_class": student.school_class_id == r.school_class_id} if student else None,
        # Who this child's parents already are, so an admin can spot a request that doesn't look right.
        "existing_parents": parents_by_student.get(student.id, []) if student else [],
        "has_account": r.email.lower() in parent_emails,
    }


def _requests(school, status="pending"):
    rows = list(ParentSignupRequest.objects.filter(school=school, status=status)
                .select_related("student__school_class", "school_class")[:500])
    parents_by_student = {}
    for g in Guardian.objects.filter(school=school, students__in=[r.student_id for r in rows if r.student_id]) \
            .prefetch_related("students"):
        for s in g.students.all():
            parents_by_student.setdefault(s.id, []).append(g.name)
    parent_emails = {e.lower() for e in User.objects.filter(guardian__school=school).values_list("email", flat=True)}
    return [_row(r, parents_by_student, parent_emails) for r in rows]


def approve(signup, admin):
    """Invite the parent (or add the child to their existing account). Returns a sentence for the admin."""
    school = signup.school
    student = signup.student
    if student is None:
        raise ValidationError(f"No student at the school has admission number {signup.admission_number}, "
                              "so there's no child to link. Turn this request down or add the student first.")
    user = User.objects.filter(email__iexact=signup.email).filter(guardian__school=school).first()
    if User.objects.filter(email__iexact=signup.email, profile__school=school).exists():
        raise ValidationError(f"{signup.email} belongs to a staff account at the school, so it can't be a "
                              "parent login too.")
    if user:
        user.guardian.students.add(student)
        send_child_added_email(user.guardian, student)
        result = f"Added {student_name(student)} to {user.guardian.name}'s account and emailed them."
    else:
        invite = GuardianInvite.objects.filter(school=school, email__iexact=signup.email,
                                               accepted_at__isnull=True).first()
        if invite:
            invite.students.add(student)
            invite.phone = invite.phone or signup.phone
            invite.relationship = invite.relationship or signup.relationship
            invite.save(update_fields=["phone", "relationship"])
            invite.renew()
        else:
            invite = GuardianInvite.objects.create(school=school, name=signup.name, email=signup.email,
                                                   phone=signup.phone, relationship=signup.relationship,
                                                   invited_by=admin)
            invite.students.add(student)
        send_invite_email(invite)
        result = f"Emailed {signup.name} an invite link for {student_name(student)}."
    signup.status = ParentSignupRequest.Status.APPROVED
    signup.decided_by, signup.decided_at = admin, timezone.now()
    signup.save(update_fields=["status", "decided_by", "decided_at"])
    log_activity(school=school, actor=admin, action="signup_request.approved", target=student,
                 summary=f"Approved {signup.name} ({signup.email}) as a parent of {student_name(student)}",
                 email=signup.email)
    return result


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, HasSchoolProfile, IsSchoolAdmin])
def signup_requests(request):
    """
    GET ?status=pending|approved|rejected: sign-up requests. POST {ids,
    decision: "approve" | "reject"}: decide one or many; approving emails
    each parent their invite link.
    """
    school = request.user.profile.school
    if request.method == "GET":
        status = request.query_params.get("status", "pending")
        if status not in ParentSignupRequest.Status.values:
            raise ValidationError({"status": "Unknown status."})
        return Response(_requests(school, status))

    ids = request.data.get("ids")
    decision = request.data.get("decision")
    if not isinstance(ids, list) or not ids or decision not in ("approve", "reject"):
        raise ValidationError("Send the request ids and a decision (approve or reject).")
    signups = list(ParentSignupRequest.objects.filter(school=school, status="pending", id__in=ids)
                   .select_related("student", "school"))
    done, problems = [], []
    for signup in signups:
        if decision == "reject":
            signup.status = ParentSignupRequest.Status.REJECTED
            signup.decided_by, signup.decided_at = request.user, timezone.now()
            signup.save(update_fields=["status", "decided_by", "decided_at"])
            log_activity(school=school, actor=request.user, action="signup_request.rejected",
                         summary=f"Turned down the parent sign-up from {signup.name} ({signup.email})",
                         email=signup.email)
            done.append(f"Turned down {signup.name}.")
            continue
        try:
            with transaction.atomic():
                done.append(approve(signup, request.user))
        except ValidationError as exc:
            problems.append(f"{signup.name}: {' '.join(str(d) for d in exc.detail)}")
    return Response({"done": done, "problems": problems, "requests": _requests(school)})
