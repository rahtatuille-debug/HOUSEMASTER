"""
Mark sheets: a teacher downloads an Excel sheet listing a class (admission number and name), types in each
student's mark, and uploads it. The upload is checked first (a preview, nothing saved) and then imported.

The same rules as typing marks one at a time apply (gradebook.views.GradeViewSet): only a class and subject the
teacher may grade, not in a locked term, only students in that class who take the subject, and no mark below 0
or above the "out of". A blank mark, or ABS / absent / -, is skipped rather than recorded as 0.
"""
from decimal import Decimal, InvalidOperation
from io import BytesIO

import openpyxl
from django.db import transaction
from openpyxl.styles import Font, PatternFill

from activity.services import log_activity, student_name
from reporting.spreadsheets import append_row
from students.models import Student

from .choices import takes
from .models import Grade

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
# Rows looked at, blank ones included, before giving up: a sheet can hold a million empty rows.
MAX_SCANNED_ROWS = 10 * MAX_ROWS
SKIP_WORDS = {"", "-", "abs", "absent", "x", "n/a", "na"}
HEADER = ["Admission no.", "Student", "Mark"]


class MarkSheetError(Exception):
    """The file can't be read at all."""


def class_students(school_class, subject):
    """The active students in the class who take the subject, in the class list's order."""
    students = Student.objects.filter(school_class=school_class, is_active=True) \
        .select_related("school", "school_class__year_group").order_by("last_name", "first_name", "id")
    return [s for s in students if takes(s, subject)]


def template(school_class, subject, term, kind, max_score):
    """The class's mark sheet: a few lines saying what it's for, then one row per student with a blank mark."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Marks"
    title = f"{subject.name} · {school_class.name} · {term.name}"
    append_row(ws, [title])
    ws["A1"].font = Font(bold=True, size=13)
    append_row(ws, [f"Assessment: {kind.name if kind else 'No type'} · Out of {max_score:g}"])
    append_row(ws, ["Type each mark in the Mark column. Leave it blank, or write ABS, for a student who has none."])
    append_row(ws, [])
    append_row(ws, HEADER)
    for cell in ws[5]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="F2EDE1")
    for s in class_students(school_class, subject):
        append_row(ws, [s.external_id or "", f"{s.first_name} {s.last_name}", None])
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 32
    ws.column_dimensions["C"].width = 10
    ws.freeze_panes = "A6"
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def read_rows(upload):
    """[(row number, admission number, mark text)] from the sheet under its header row."""
    from housemaster.uploads import MARK_SHEET_MAX_UNPACKED, UnsafeWorkbook, check_xlsx

    if upload.size > MAX_BYTES:
        raise MarkSheetError("The file must be smaller than 2 MB.")
    try:
        check_xlsx(upload, MARK_SHEET_MAX_UNPACKED)
    except UnsafeWorkbook as exc:
        raise MarkSheetError(str(exc))
    try:
        wb = openpyxl.load_workbook(upload, read_only=True, data_only=True)
    except Exception:
        raise MarkSheetError("That isn't an Excel file HouseMaster can read. Save it as .xlsx and try again.")
    ws = wb["Marks"] if "Marks" in wb.sheetnames else wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    columns = None
    for number, row in enumerate(rows, start=1):
        cells = [_cell_text(v).lower() for v in row]
        if any(c.startswith("admission") for c in cells) and any(c.startswith("mark") for c in cells):
            columns = (next(i for i, c in enumerate(cells) if c.startswith("admission")),
                       next(i for i, c in enumerate(cells) if c.startswith("mark")))
            break
        if number > 20:
            break
    if columns is None:
        raise MarkSheetError('Couldn\'t find the "Admission no." and "Mark" columns. Download the mark sheet and use '
                             "that.")
    out = []
    for number, row in enumerate(rows, start=number + 1):
        if number > MAX_SCANNED_ROWS:
            raise MarkSheetError(f"The sheet has more than {MAX_SCANNED_ROWS} rows, most of them empty. "
                                 "Delete the empty rows and try again.")
        row = list(row)
        admission = _cell_text(row[columns[0]]) if columns[0] < len(row) else ""
        mark = _cell_text(row[columns[1]]) if columns[1] < len(row) else ""
        if not admission and not mark:
            continue
        out.append((number, admission, mark))
        if len(out) > MAX_ROWS:
            raise MarkSheetError(f"The sheet has more than {MAX_ROWS} rows.")
    return out


def check(upload, school_class, subject, term, kind, max_score):
    """Every row's outcome, the marks ready to save, and the class's students with no mark in the file."""
    rows = read_rows(upload)
    students = {s.external_id.strip().lower(): s for s in Student.objects.filter(school=school_class.year_group.school)
                .exclude(external_id="").select_related("school", "school_class__year_group")}
    takers = {s.id for s in class_students(school_class, subject)}
    results, ready, seen = [], [], set()
    for number, admission, mark in rows:
        student = students.get(admission.lower())
        row = {"row": number, "admission_number": admission, "name": student_name(student) if student else "",
               "mark": mark, "status": "error", "message": ""}
        results.append(row)
        if student is None:
            row["message"] = "No student has this admission number."
            continue
        if student.school_class_id != school_class.id or not student.is_active:
            row["message"] = f"Not in {school_class.name}."
            continue
        if student.id not in takers:
            row["message"] = f"Doesn't take {subject.name}."
            continue
        if student.id in seen:
            row["message"] = "This student is in the sheet twice."
            continue
        seen.add(student.id)
        if mark.lower() in SKIP_WORDS:
            row.update(status="skipped", message="No mark: skipped.")
            continue
        try:
            score = Decimal(mark.replace(",", "."))
        except InvalidOperation:
            row["message"] = "The mark isn't a number."
            continue
        if not score.is_finite() or score < 0 or score > max_score:
            row["message"] = f"The mark must be between 0 and {max_score:g}."
            continue
        row.update(status="ok", mark=f"{score:g}")
        ready.append(Grade(student=student, subject=subject, term=term, assessment_type=kind,
                           score=score.quantize(Decimal("0.01")), max_score=max_score))
    missing = [student_name(s) for s in class_students(school_class, subject) if s.id not in seen]
    counts = {"ready": len(ready), "skipped": sum(r["status"] == "skipped" for r in results),
              "errors": sum(r["status"] == "error" for r in results), "missing": len(missing)}
    return {"rows": results, "counts": counts, "missing": missing}, ready


def import_marks(upload, user, school_class, subject, term, kind, max_score, commit):
    result, ready = check(upload, school_class, subject, term, kind, max_score)
    result["imported"] = 0
    if commit and ready:
        with transaction.atomic():
            Grade.objects.bulk_create(ready)
        result["imported"] = len(ready)
        log_activity(
            school=school_class.year_group.school, actor=user, action="grade.imported",
            summary=f"Imported {len(ready)} {subject.name} marks for {school_class.name} ({term.name}"
                    f"{', ' + kind.name if kind else ''}, out of {max_score:g}) from {getattr(upload, 'name', 'a file')}",
            count=len(ready), subject=subject.id, school_class=school_class.id, term=term.id,
        )
    return result
