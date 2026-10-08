"""An invoice as a one-page PDF."""
from django.conf import settings
from fpdf import FPDF

from reporting.exports import FONT_DIR


def invoice_pdf(invoice):
    school = invoice.school
    pdf = FPDF(format="A4")
    pdf.add_font("Serif", "", str(FONT_DIR / "DejaVuSerif.ttf"))
    pdf.add_font("Serif", "B", str(FONT_DIR / "DejaVuSerif-Bold.ttf"))
    pdf.set_margins(20, 20, 20)
    pdf.add_page()
    pdf.set_font("Serif", "B", 18)
    pdf.cell(0, 10, "HouseMaster", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Serif", "", 10)
    pdf.cell(0, 6, "Subscription invoice", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    rows = [
        ("Invoice", invoice.number), ("School", school.name), ("Issued", f"{invoice.issued_on:%d %B %Y}"),
        ("Due", f"{invoice.due_on:%d %B %Y}"),
        ("Period", f"{invoice.period_start:%d %B %Y} to {invoice.period_end:%d %B %Y}"),
        ("Plan", f"{invoice.plan_name} ({invoice.students} active students)"),
        ("Amount", f"{invoice.currency} {invoice.amount:,.2f}"),
        ("Status", invoice.get_status_display() + (f" on {invoice.paid_on:%d %B %Y}" if invoice.paid_on else "")),
    ]
    for label, value in rows:
        pdf.set_font("Serif", "B", 10)
        pdf.cell(35, 7, label)
        pdf.set_font("Serif", "", 10)
        pdf.multi_cell(0, 7, value, new_x="LMARGIN", new_y="NEXT")
    how = settings.BILLING_PAYMENT_INSTRUCTIONS.strip()
    if how and invoice.status == "open":
        pdf.ln(6)
        pdf.set_font("Serif", "B", 11)
        pdf.cell(0, 7, "How to pay", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Serif", "", 10)
        pdf.multi_cell(0, 6, f"{how}\nPlease use {invoice.number} as the reference.", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
