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
    template_workbook().save(out)
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
