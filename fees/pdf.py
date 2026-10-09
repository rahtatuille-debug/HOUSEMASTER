"""A fee receipt as a one-page PDF."""
from fpdf import FPDF

from reporting.exports import FONT_DIR

from . import services


def receipt_pdf(payment):
    school, student = payment.school, payment.student
    currency = services.settings_for(school).currency
    pdf = FPDF(format="A5")
    pdf.add_font("Serif", "", str(FONT_DIR / "DejaVuSerif.ttf"))
    pdf.add_font("Serif", "B", str(FONT_DIR / "DejaVuSerif-Bold.ttf"))
    pdf.set_margins(15, 15, 15)
    pdf.add_page()
    pdf.set_font("Serif", "B", 15)
    pdf.multi_cell(0, 8, school.name, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Serif", "", 9)
    for line in (school.address, school.phone, school.email):
        if line:
            pdf.multi_cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Serif", "B", 12)
    pdf.cell(0, 8, ("VOID - " if payment.voided_at else "") + "Fees receipt", new_x="LMARGIN", new_y="NEXT")
    rows = [
        ("Receipt", payment.receipt_number), ("Student", f"{student.first_name} {student.last_name}"),
        ("Class", student.school_class.name if student.school_class_id else ""),
        ("Admission no.", student.external_id or ""), ("Amount", services.money(payment.amount, currency)),
        ("Paid on", f"{payment.paid_on:%d %B %Y}"), ("Method", payment.get_method_display()),
        ("Reference", payment.reference), ("Paid by", payment.payer_name), ("Recorded by", payment.recorded_by_name),
    ]
    for label, value in rows:
        if not value:
            continue
        pdf.set_font("Serif", "B", 9)
        pdf.cell(32, 6, label)
        pdf.set_font("Serif", "", 9)
        pdf.multi_cell(0, 6, value, new_x="LMARGIN", new_y="NEXT")
    if payment.voided_at:
        pdf.ln(3)
        pdf.set_font("Serif", "B", 9)
        pdf.multi_cell(0, 6, f"This payment was cancelled: {payment.void_reason}", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
