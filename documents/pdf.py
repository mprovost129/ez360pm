from io import BytesIO
from xml.sax.saxutils import escape

from django.utils.html import strip_tags
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _money(value):
    return f"${value:,.2f}"


def _pdf_rich_text(value):
    value = value or ""
    for ending in ("</p>", "</li>", "<br>", "<br/>", "<br />"):
        value = value.replace(ending, "\n")
    return escape(strip_tags(value)).replace("\n", "<br/>")


def build_invoice_pdf(invoice):
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.65 * inch,
        leftMargin=0.65 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title=f"Invoice {invoice.number}",
        author=invoice.company.name,
    )
    styles = getSampleStyleSheet()
    right = ParagraphStyle("Right", parent=styles["Normal"], alignment=TA_RIGHT)
    story = []

    company_lines = [invoice.company.name]
    company_lines.extend(
        value
        for value in (
            invoice.company.address_1,
            invoice.company.address_2,
            " ".join(
                part
                for part in (
                    invoice.company.city,
                    invoice.company.state,
                    invoice.company.postal_code,
                )
                if part
            ),
            invoice.company.phone,
            invoice.company.email,
        )
        if value
    )
    header = Table(
        [
            [
                Paragraph("<br/>".join(escape(line) for line in company_lines), styles["Normal"]),
                Paragraph(f"<b>INVOICE</b><br/>{escape(invoice.number)}", right),
            ]
        ],
        colWidths=[4.7 * inch, 2.0 * inch],
    )
    story.extend([header, Spacer(1, 0.3 * inch)])

    client = invoice.project.client
    contact = client.primary_contact
    bill_to = [client.display_name]
    if contact:
        bill_to.extend((contact.get_full_name(), contact.email))
    bill_to.extend(
        value
        for value in (
            client.billing_address_1,
            client.billing_address_2,
            " ".join(
                part
                for part in (
                    client.billing_city,
                    client.billing_state,
                    client.billing_postal_code,
                )
                if part
            ),
        )
        if value
    )
    details = Table(
        [
            [Paragraph("<b>Bill to</b>", styles["Normal"]), Paragraph("<b>Details</b>", styles["Normal"])],
            [
                Paragraph("<br/>".join(escape(line) for line in bill_to), styles["Normal"]),
                Paragraph(
                    f"Project: {escape(invoice.project.number)} - {escape(invoice.project.name)}<br/>"
                    f"Issued: {invoice.issue_date:%B %d, %Y}<br/>Due: {invoice.due_date:%B %d, %Y}",
                    styles["Normal"],
                ),
            ],
        ],
        colWidths=[3.35 * inch, 3.35 * inch],
    )
    story.extend([details, Spacer(1, 0.3 * inch)])

    rows = [["Description", "Qty", "Rate", "Tax", "Amount"]]
    for line in invoice.line_items.all():
        rows.append(
            [
                Paragraph(escape(line.description), styles["Normal"]),
                f"{line.quantity}",
                _money(line.rate),
                f"{line.tax_rate}%",
                _money(line.line_total),
            ]
        )
    lines = Table(rows, colWidths=[3.25 * inch, 0.7 * inch, 1 * inch, 0.7 * inch, 1.05 * inch], repeatRows=1)
    lines.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324d")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#d8e0e6")),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.extend([lines, Spacer(1, 0.2 * inch)])

    totals = [
        ["Subtotal", _money(invoice.subtotal)],
        ["Tax", _money(invoice.tax_total)],
    ]
    if invoice.credit_total:
        totals.append(["Retainer credits", f"-{_money(invoice.credit_total)}"])
    totals.extend(
        [
            ["Total", _money(invoice.total)],
            ["Paid", _money(invoice.amount_paid)],
            ["Balance due", _money(invoice.outstanding_balance)],
        ]
    )
    totals_table = Table(totals, colWidths=[1.4 * inch, 1.1 * inch], hAlign="RIGHT")
    totals_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#17324d")),
            ]
        )
    )
    story.append(totals_table)
    if invoice.terms:
        story.extend(
            [
                Spacer(1, 0.3 * inch),
                Paragraph("<b>Terms</b>", styles["Normal"]),
                Paragraph(escape(invoice.terms).replace("\n", "<br/>"), styles["Normal"]),
            ]
        )
    if invoice.notes:
        story.extend(
            [
                Spacer(1, 0.2 * inch),
                Paragraph("<b>Notes</b>", styles["Normal"]),
                Paragraph(escape(invoice.notes).replace("\n", "<br/>"), styles["Normal"]),
            ]
        )
    document.build(story)
    return buffer.getvalue()


def build_proposal_pdf(proposal):
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.7 * inch,
        leftMargin=0.7 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
        title=f"Proposal {proposal.number}",
        author=proposal.company.name,
    )
    styles = getSampleStyleSheet()
    right = ParagraphStyle("ProposalRight", parent=styles["Normal"], alignment=TA_RIGHT)
    story = [
        Table(
            [
                [
                    Paragraph(f"<b>{escape(proposal.company.name)}</b>", styles["Title"]),
                    Paragraph(f"<b>PROPOSAL</b><br/>{escape(proposal.number)}", right),
                ]
            ],
            colWidths=[4.7 * inch, 1.7 * inch],
        ),
        Spacer(1, 0.25 * inch),
        Paragraph(
            f"<b>Prepared for:</b> {escape(proposal.project.client.display_name)}<br/>"
            f"<b>Project:</b> {escape(proposal.project.number)} - {escape(proposal.project.name)}<br/>"
            f"<b>Site:</b> {escape(proposal.project.address_1)}, "
            f"{escape(proposal.project.city)}, {escape(proposal.project.state)} "
            f"{escape(proposal.project.postal_code)}<br/>"
            f"<b>Issued:</b> {proposal.issue_date:%B %d, %Y}",
            styles["Normal"],
        ),
        Spacer(1, 0.3 * inch),
    ]
    for section in proposal.body_sections:
        story.append(Paragraph(escape(section.get("heading", "")), styles["Heading2"]))
        story.append(Paragraph(_pdf_rich_text(section.get("body", "")), styles["BodyText"]))
        story.append(Spacer(1, 0.15 * inch))

    rows = [["Description", "Qty", "Rate", "Amount"]]
    for line in proposal.line_items.all():
        rows.append(
            [
                Paragraph(escape(line.description), styles["Normal"]),
                str(line.quantity),
                _money(line.rate),
                _money(line.line_total),
            ]
        )
    pricing = Table(rows, colWidths=[3.7 * inch, 0.8 * inch, 1 * inch, 1.1 * inch], repeatRows=1)
    pricing.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324d")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#d8e0e6")),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.extend(
        [
            pricing,
            Spacer(1, 0.15 * inch),
            Table(
                [["Proposal total", _money(proposal.total)]],
                colWidths=[1.4 * inch, 1.1 * inch],
                hAlign="RIGHT",
                style=TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                        ("LINEABOVE", (0, 0), (-1, 0), 1, colors.HexColor("#17324d")),
                    ]
                ),
            ),
        ]
    )
    if proposal.terms:
        story.extend(
            [
                Spacer(1, 0.3 * inch),
                Paragraph("Terms", styles["Heading3"]),
                Paragraph(_pdf_rich_text(proposal.terms), styles["BodyText"]),
            ]
        )
    document.build(story)
    return buffer.getvalue()
