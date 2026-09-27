"""
Downloads for a class: class list, grades and attendance as Excel
workbooks, and finalized reports as one PDF (a page per student).

Callers pass in students already limited to what the requester may see
(accounts.scoping), so this module never decides who sees what.
"""
from collections import defaultdict
from datetime import date
from io import BytesIO
from pathlib import Path

import openpyxl
from fpdf import FPDF
from fpdf.fonts import FontFace
from openpyxl.styles import Alignment, Font, PatternFill

from attendance.models import AttendanceRecord
from gradebook.models import Grade

from .models import StudentReport

HEADER_FILL = PatternFill("solid", fgColor="1E2F52")
HEADER_FONT = Font(bold=True, color="FAF7F0")
FONT_DIR = Path(__file__).resolve().parent / "fonts"
GENDERS = {"female": "Female", "male": "Male", "other": "Other"}
MODES = {"day": "Day", "boarding": "Boarding"}


def _name(student):
    return f"{student.first_name} {student.last_name}"


def _sheet(wb, title, headers, rows, widths=None):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for cell in ws[1]:
        cell.fill, cell.font = HEADER_FILL, HEADER_FONT
        cell.alignment = Alignment(vertical="center")
    for row in rows:
        ws.append(row)
    ws.freeze_panes = "A2"
    for i, header in enumerate(headers, start=1):
        width = (widths or {}).get(header) or max(10, min(40, len(str(header)) + 4))
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = width
    return ws


def _workbook_bytes(wb):
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def class_list_xlsx(students):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    rows = []
    for s in students:
        parents = [g for g in s.guardians.all() if g.user.is_active]
        rows.append([
            s.external_id, s.last_name, s.first_name, GENDERS.get(s.gender, ""), s.date_of_birth,
            s.house, MODES.get(s.mode_of_learning, ""), s.enrolled_on, "Active" if s.is_active else "Inactive",
            "; ".join(g.name for g in parents), "; ".join(g.user.email for g in parents),
            "; ".join(g.phone for g in parents if g.phone), s.medical_notes,
        ])
    ws = _sheet(wb, "Class list", [
        "Admission no.", "Last name", "First name", "Gender", "Date of birth", "House", "Mode of learning",
        "Admission date", "Status", "Parents", "Parent emails", "Parent phones", "Health notes",
    ], rows, widths={"Parents": 28, "Parent emails": 32, "Parent phones": 22, "Health notes": 40})
    for row in ws.iter_rows(min_row=2):
        for cell in (row[4], row[7]):
            cell.number_format = "yyyy-mm-dd"
    return _workbook_bytes(wb)


def grades_xlsx(students, term):
    grades = Grade.objects.filter(student__in=students, term=term).select_related("subject")
    by_student = defaultdict(dict)
    subjects = set()
    for g in grades:
        percent = round(float(g.score) / float(g.max_score) * 100, 1) if g.max_score else None
        by_student[g.student_id][g.subject.name] = percent
        subjects.add(g.subject.name)
    subjects = sorted(subjects)
    rows = []
    for s in students:
        marks = [by_student[s.id].get(subj) for subj in subjects]
        present = [m for m in marks if m is not None]
        rows.append([s.external_id, s.last_name, s.first_name, *marks,
                     round(sum(present) / len(present), 1) if present else None])
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    _sheet(wb, "Grades (%)", ["Admission no.", "Last name", "First name", *subjects, "Average"], rows)
    return _workbook_bytes(wb)


def attendance_xlsx(students, start, end):
    records = AttendanceRecord.objects.filter(student__in=students, date__gte=start, date__lte=end)
    by_student = defaultdict(dict)
    days = set()
    for r in records:
        by_student[r.student_id][r.date] = r.status
        days.add(r.date)
    days = sorted(days)
    letters = {"present": "P", "absent": "A", "late": "L", "excused": "E"}

    summary = []
    for s in students:
        statuses = list(by_student[s.id].values())
        counts = {k: statuses.count(k) for k in letters}
        total = len(statuses)
        rate = round((counts["present"] + counts["late"]) / total * 100, 1) if total else None
        summary.append([s.external_id, s.last_name, s.first_name, total, counts["present"], counts["absent"],
                        counts["late"], counts["excused"], rate])
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    _sheet(wb, "Summary", ["Admission no.", "Last name", "First name", "Days recorded", "Present", "Absent",
                           "Late", "Excused", "Attendance % (present or late)"],
           summary, widths={"Attendance % (present or late)": 30})
    grid = [[s.external_id, _name(s), *[letters.get(by_student[s.id].get(d), "") for d in days]] for s in students]
    ws = _sheet(wb, "By day", ["Admission no.", "Student", *[d.strftime("%a %d %b") for d in days]], grid,
                widths={"Student": 26})
    ws.append([])
    ws.append(["P = present, A = absent, L = late, E = excused"])
    return _workbook_bytes(wb)


class _ReportPDF(FPDF):
    def __init__(self, school_name):
        super().__init__(format="A4")
        self.school_name = school_name
        self.add_font("Serif", "", str(FONT_DIR / "DejaVuSerif.ttf"))
        self.add_font("Serif", "B", str(FONT_DIR / "DejaVuSerif-Bold.ttf"))
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(18, 16, 18)

    def footer(self):
        self.set_y(-12)
        self.set_font("Serif", "", 8)
        self.set_text_color(110, 110, 110)
        self.cell(0, 6, f"{self.school_name} · Page {self.page_no()}", align="C")


def reports_pdf(school, students, term):
    """One page per student with a finalized report for the term. Returns (bytes, count)."""
    reports = {
        r.student_id: r
        for r in StudentReport.objects.filter(student__in=students, term=term, status="finalized")
    }
    grades = defaultdict(list)
    for g in Grade.objects.filter(student__in=students, term=term).select_related("subject").order_by("subject__name"):
        grades[g.student_id].append(g)
    attendance = defaultdict(lambda: defaultdict(int))
    if term.start_date and term.end_date:
        for r in AttendanceRecord.objects.filter(student__in=students, date__gte=term.start_date,
                                                 date__lte=term.end_date):
            attendance[r.student_id][r.status] += 1

    pdf = _ReportPDF(school.name)
    count = 0
    navy, gold, ink = (30, 47, 82), (184, 134, 46), (27, 35, 51)
    for s in students:
        report = reports.get(s.id)
        if report is None:
            continue
        count += 1
        pdf.add_page()
        pdf.set_draw_color(*gold)
        pdf.set_line_width(1.2)
        pdf.line(18, 14, 192, 14)
        pdf.set_line_width(0.2)
        pdf.set_draw_color(221, 213, 194)
        pdf.set_text_color(*navy)
        pdf.set_font("Serif", "B", 11)
        pdf.cell(0, 8, school.name.upper(), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Serif", "B", 20)
        pdf.cell(0, 11, _name(s), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Serif", "", 11)
        pdf.set_text_color(*ink)
        klass = s.school_class
        details = [f"Term: {term.name}"]
        if klass:
            details.append(f"Class: {klass.year_group.name} · {klass.name}")
        if s.external_id:
            details.append(f"Admission no.: {s.external_id}")
        pdf.cell(0, 7, "   |   ".join(details), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        if grades[s.id]:
            pdf.set_font("Serif", "B", 12)
            pdf.set_text_color(*navy)
            pdf.cell(0, 8, "Results", new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(*ink)
            pdf.set_font("Serif", "", 10)
            with pdf.table(col_widths=(90, 40, 44), text_align=("LEFT", "CENTER", "CENTER"), line_height=7,
                           headings_style=FontFace(emphasis="BOLD", fill_color=(242, 237, 225))) as table:
                table.row(["Subject", "Score", "Percent"])
                for g in grades[s.id]:
                    pct = f"{float(g.score) / float(g.max_score) * 100:.0f}%" if g.max_score else "—"
                    table.row([g.subject.name, f"{g.score.normalize():f} / {g.max_score.normalize():f}", pct])
            pdf.ln(4)

        att = attendance[s.id]
        total = sum(att.values())
        if total:
            pdf.set_font("Serif", "", 10)
            rate = (att["present"] + att["late"]) / total * 100
            pdf.cell(0, 7, f"Attendance this term: {rate:.0f}% ({att['absent']} absent, {att['late']} late, "
                           f"{att['excused']} excused, of {total} days)", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

        pdf.set_font("Serif", "B", 12)
        pdf.set_text_color(*navy)
        pdf.cell(0, 8, "Teacher's comment", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Serif", "", 11)
        pdf.set_text_color(*ink)
        pdf.multi_cell(0, 6.5, report.report_comment or "—", align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(6)
        pdf.set_font("Serif", "", 8)
        pdf.set_text_color(110, 110, 110)
        finalized = report.finalized_at.date() if report.finalized_at else date.today()
        pdf.cell(0, 5, f"Finalized {finalized:%d %B %Y}", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output()), count
