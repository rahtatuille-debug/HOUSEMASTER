"""
A subscription invoice as a one-page PDF, laid out like a classic invoice (the
owner's template): logo and INVOICE across the top, who it's from with the
dates and number beside it, the school billed with the amount due, a
description and amount table with the total, then how to pay and thank you.
"""
from pathlib import Path

from django.conf import settings
from fpdf import FPDF

from reporting.exports import FONT_DIR

LOGO = Path(__file__).resolve().parent / "assets" / "housemaster-logo.png"
INK = (40, 40, 40)
MUTED = (110, 110, 110)
RULE = (170, 170, 170)
SHADE = (236, 236, 236)
NAVY = (22, 50, 92)

LEFT, RIGHT, WIDTH = 18, 192, 174  # mm on A4
RIGHT_COL = 130  # where the right-hand column starts


def _money(amount, currency):
    return f"{currency} {amount:,.2f}"


def _lines(*values):
    out = []
    for v in values:
        out += [line.strip() for line in str(v or "").splitlines() if line.strip()]
    return out


def _description(invoice):
    period = f"{invoice.period_start:%d %b %Y} to {invoice.period_end:%d %b %Y}"
    text = f"HouseMaster subscription, {period}"
    if invoice.students:
        each = invoice.amount / invoice.students
        text += (f"\n{invoice.plan_name}: {invoice.students} active student{'s' if invoice.students != 1 else ''}"
                 f" x {_money(each, invoice.currency)} a month")
    else:
        text += f"\n{invoice.plan_name}"
    return text


class _Invoice(FPDF):
    def setup(self):
        self.add_font("Sans", "", str(FONT_DIR / "DejaVuSans.ttf"))
        self.add_font("Sans", "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))
        self.set_margins(LEFT, 16, 210 - RIGHT)
        self.set_auto_page_break(False)
        self.add_page()

    def text_at(self, x, y, w, h, text, size=9, bold=False, color=INK, align="L"):
        self.set_xy(x, y)
        self.set_font("Sans", "B" if bold else "", size)
        self.set_text_color(*color)
        self.multi_cell(w, h, text, align=align, new_x="LMARGIN", new_y="NEXT")
        return self.get_y()

    def rule(self, x1, y, x2, color=RULE, width=0.3):
        self.set_draw_color(*color)
        self.set_line_width(width)
        self.line(x1, y, x2, y)


def invoice_pdf(invoice):
    school = invoice.school
    pdf = _Invoice(format="A4")
    pdf.setup()
    s = settings

    # Logo and INVOICE.
    if LOGO.exists():
        pdf.image(str(LOGO), x=LEFT, y=14, h=24)
    else:
        pdf.text_at(LEFT, 20, 90, 10, s.BILLING_COMPANY_NAME, size=20, bold=True, color=NAVY)
    pdf.text_at(RIGHT_COL, 20, RIGHT - RIGHT_COL, 10, "INVOICE", size=22, color=MUTED, align="R")
    if invoice.status == "paid":
        pdf.text_at(RIGHT_COL, 31, RIGHT - RIGHT_COL, 6, "PAID", size=12, bold=True, color=(46, 125, 50), align="R")

    # Who it's from; the dates and number beside it.
    y = 46
    from_lines = _lines(s.BILLING_COMPANY_NAME, s.BILLING_COMPANY_ADDRESS, s.BILLING_COMPANY_PHONE, s.BILLING_COMPANY_EMAIL)
    for n, line in enumerate(from_lines):
        pdf.text_at(LEFT, y + n * 5, 95, 5, line, size=9, bold=n == 0)
    right_y = y
    for label, value in (("DATE OF INVOICE", f"{invoice.issued_on:%d %B %Y}"), ("INVOICE NO.", invoice.number),
                         ("DATE DUE", f"{invoice.due_on:%d %B %Y}")):
        pdf.text_at(RIGHT_COL, right_y, RIGHT - RIGHT_COL, 5, value, size=9, align="R")
        pdf.rule(RIGHT_COL, right_y + 5.5, RIGHT)
        pdf.text_at(RIGHT_COL, right_y + 6, RIGHT - RIGHT_COL, 4, label, size=7, bold=True, color=MUTED, align="R")
        right_y += 13

    # The school billed, and the amount.
    y = max(y + len(from_lines) * 5, right_y) + 6
    pdf.text_at(LEFT, y, 95, 4, "BILLED TO", size=7, bold=True, color=MUTED)
    pdf.rule(LEFT, y + 5, LEFT + 95)
    to_lines = _lines(school.name, school.address, school.phone, school.email)
    for n, line in enumerate(to_lines):
        pdf.text_at(LEFT, y + 7 + n * 5, 95, 5, line, size=9, bold=n == 0)
    pdf.text_at(RIGHT_COL, y, RIGHT - RIGHT_COL, 4, "AMOUNT DUE" if invoice.status == "open" else "AMOUNT",
                size=7, bold=True, color=MUTED, align="R")
    pdf.rule(RIGHT_COL, y + 5, RIGHT)
    pdf.text_at(RIGHT_COL, y + 7, RIGHT - RIGHT_COL, 7, _money(invoice.amount, invoice.currency), size=13, bold=True, align="R")

    # Description and amount.
    y = y + 9 + max(len(to_lines), 2) * 5 + 4
    amount_x = RIGHT - 42
    pdf.set_fill_color(*SHADE)
    pdf.set_draw_color(*RULE)
    pdf.rect(LEFT, y, WIDTH, 7, style="DF")
    pdf.text_at(LEFT, y + 1.5, amount_x - LEFT, 4, "DESCRIPTION", size=7, bold=True, align="C")
    pdf.text_at(amount_x, y + 1.5, RIGHT - amount_x, 4, "AMOUNT", size=7, bold=True, align="C")
    body_top, body_h = y + 7, 92
    pdf.rect(LEFT, body_top, WIDTH, body_h)
    pdf.rect(amount_x, body_top, RIGHT - amount_x, body_h, style="F")
    pdf.rect(amount_x, body_top, RIGHT - amount_x, body_h)
    pdf.text_at(LEFT + 3, body_top + 3, amount_x - LEFT - 6, 5, _description(invoice), size=9)
    pdf.text_at(amount_x, body_top + 3, RIGHT - amount_x - 3, 5, _money(invoice.amount, invoice.currency), size=9, align="R")
    total_y = body_top + body_h
    pdf.text_at(LEFT, total_y + 2.5, amount_x - LEFT - 3, 5, "TOTAL", size=8, bold=True, align="R")
    pdf.rect(amount_x, total_y, RIGHT - amount_x, 9)
    pdf.text_at(amount_x, total_y + 2, RIGHT - amount_x - 3, 5, _money(invoice.amount, invoice.currency), size=10,
                bold=True, align="R")

    # Status, how to pay, thank you, contact.
    y = total_y + 16
    if invoice.status == "paid":
        paid = f"Paid on {invoice.paid_on:%d %B %Y}" if invoice.paid_on else "Paid"
        if invoice.payment_method:
            paid += f" by {invoice.get_payment_method_display()}"
        if invoice.payment_reference:
            paid += f" (ref. {invoice.payment_reference})"
        y = pdf.text_at(LEFT, y, WIDTH, 5, paid + ". Thank you.", size=9, bold=True, color=(46, 125, 50), align="C") + 2
    elif s.BILLING_PAYMENT_INSTRUCTIONS.strip():
        y = pdf.text_at(LEFT + 10, y, WIDTH - 20, 4.5,
                        f"How to pay: {s.BILLING_PAYMENT_INSTRUCTIONS.strip()}\nPlease use {invoice.number} as the reference.",
                        size=8, color=MUTED, align="C") + 2
    pdf.text_at(LEFT, y + 2, WIDTH, 8, "THANK YOU", size=15, align="C")
    contact = ", ".join(_lines(s.BILLING_COMPANY_NAME, s.BILLING_COMPANY_PHONE, s.BILLING_COMPANY_EMAIL))
    y = pdf.text_at(LEFT, y + 13, WIDTH, 4.5, f"For questions concerning this invoice, please contact\n{contact}",
                    size=8, color=MUTED, align="C")
    website = s.BILLING_COMPANY_WEBSITE or s.FRONTEND_URL
    if website:
        pdf.text_at(LEFT, y + 1, WIDTH, 4.5, website.replace("https://", "").replace("http://", "").rstrip("/"),
                    size=8, color=MUTED, align="C")
    return bytes(pdf.output())
