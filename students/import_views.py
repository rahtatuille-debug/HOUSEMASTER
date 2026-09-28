from io import BytesIO

from django.http import HttpResponse
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import HasSchoolProfile, IsSchoolAdmin
from activity.services import log_activity

from .importer import WorkbookError, import_workbook, template_workbook

MAX_BYTES = 10 * 1024 * 1024
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@api_view(["GET"])
@permission_classes([IsAuthenticated, HasSchoolProfile, IsSchoolAdmin])
def import_template(request):
    """An empty workbook with the right sheets and columns, and an example row."""
    out = BytesIO()
    template_workbook(request.user.profile.school).save(out)
    response = HttpResponse(out.getvalue(), content_type=XLSX)
    response["Content-Disposition"] = 'attachment; filename="housemaster-import-template.xlsx"'
    return response


@api_view(["POST"])
@permission_classes([IsAuthenticated, HasSchoolProfile, IsSchoolAdmin])
@parser_classes([MultiPartParser])
def import_school_workbook(request):
    """
    Upload a workbook as `file`. With `commit` absent or "false" this is a
    preview: everything is checked and counted but nothing is saved. With
    `commit=true` the rows without errors are imported into the admin's own
    school.
    """
    upload = request.FILES.get("file")
    if upload is None:
        raise ValidationError({"file": "Choose an Excel file to upload."})
    if upload.size > MAX_BYTES:
        raise ValidationError({"file": "The file must be smaller than 10 MB."})
    commit = str(request.data.get("commit", "")).lower() == "true"
    school = request.user.profile.school
    try:
        result = import_workbook(upload, school, commit=commit)
    except WorkbookError as exc:
        raise ValidationError({"file": str(exc)})
    if commit:
        c = result["counts"]
        log_activity(
            school=school, actor=request.user, action="school.imported",
            summary=f'Imported "{upload.name}": {c["students_created"]} new students, '
            f'{c["students_updated"]} updated, {c["grades"]} grades, {c["attendance"]} attendance records',
            **c, errors=len(result["errors"]),
        )
    return Response(result)


@api_view(["GET"])
@permission_classes([IsAuthenticated, HasSchoolProfile, IsSchoolAdmin])
def staff_import_template(request):
    """An empty staff sheet with the right columns and two example rows."""
    from accounts.staff_import import staff_template

    out = BytesIO()
    staff_template(request.user.profile.school).save(out)
    response = HttpResponse(out.getvalue(), content_type=XLSX)
    response["Content-Disposition"] = 'attachment; filename="housemaster-staff-template.xlsx"'
    return response


@api_view(["POST"])
@permission_classes([IsAuthenticated, HasSchoolProfile, IsSchoolAdmin])
@parser_classes([MultiPartParser])
def import_staff(request):
    """
    Upload a staff sheet as `file`. Without `commit=true` it's a preview and
    nothing is saved. With `commit=true` each new person gets a staff invite
    (with their classes assigned when they accept), and with `send_emails=true`
    each is also emailed their invite link.
    """
    from django.conf import settings

    from accounts.staff_import import import_staff as run_import
    from guardians.notifications import send_after_commit

    upload = request.FILES.get("file")
    if upload is None:
        raise ValidationError({"file": "Choose an Excel file to upload."})
    if upload.size > MAX_BYTES:
        raise ValidationError({"file": "The file must be smaller than 10 MB."})
    commit = str(request.data.get("commit", "")).lower() == "true"
    send_emails = str(request.data.get("send_emails", "")).lower() == "true"
    school = request.user.profile.school
    try:
        result = run_import(upload, school, request.user, commit=commit)
    except WorkbookError as exc:
        raise ValidationError({"file": str(exc)})
    if commit and (result["people"] or result["deferred"]):
        # Deferred rows by number only: no names or addresses in the log.
        deferred_rows = [d["row"] for d in result["deferred"]]
        log_activity(
            school=school, actor=request.user, action="staff.imported",
            summary=f'Imported "{upload.name}": invited {len(result["people"])} staff'
                    + (" and emailed their invite links" if send_emails and result["people"] else "")
                    + (f"; rows {', '.join(map(str, deferred_rows))} deferred (invite limit reached)"
                       if deferred_rows else ""),
            invited=len(result["people"]), skipped=len(result["skipped"]), errors=len(result["errors"]),
            deferred_rows=deferred_rows,
        )
        if send_emails and result["people"]:
            messages = [(
                f"You're invited to join {school.name} on HouseMaster",
                f"Hello {p['name']},\n\n{request.user.profile.name} has invited you to join {school.name} on "
                f"HouseMaster as {'an admin' if p['role'] == 'admin' else 'a teacher'}.\n\n"
                f"Create your account here (the link works for 7 days):\n"
                f"{settings.FRONTEND_URL}/invite/{p['token']}\n",
                p["email"],
            ) for p in result["people"]]

            def done(sent, attempted):
                log_activity(school=school, actor=request.user, action="notification.emailed",
                             summary=f"Emailed {sent} of {attempted} staff invite links")

            send_after_commit(messages, done)
    return Response(result)
