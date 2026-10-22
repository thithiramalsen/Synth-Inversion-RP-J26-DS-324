"""Build the editable logbook text and printable weekly record from one source."""
from datetime import date
from html import escape
import json
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STEM = "C2_Research_Logbook_2026-08-03_to_2026-10-20"
DATA = json.loads((HERE / "logbook_entries.json").read_text(encoding="utf-8"))
PDF = ROOT / "output/pdf" / (STEM + ".pdf")
MD = HERE / (STEM + ".md")

for name, filename in (("LogSans", "calibri.ttf"), ("LogSans-Bold", "calibrib.ttf")):
    pdfmetrics.registerFont(TTFont(name, str(Path("C:/Windows/Fonts") / filename)))
pdfmetrics.registerFontFamily("LogSans", normal="LogSans", bold="LogSans-Bold")

BODY = ParagraphStyle("Body", fontName="LogSans", fontSize=11, leading=14,
                      textColor=colors.black, spaceAfter=5)
CELL = ParagraphStyle("Cell", parent=BODY, fontSize=10.6, leading=13.2, spaceAfter=0)
DATE = ParagraphStyle("Date", parent=CELL, fontName="LogSans-Bold", fontSize=10.2)
SMALL = ParagraphStyle("Small", parent=BODY, fontSize=9, leading=11.5, spaceAfter=3)
H1 = ParagraphStyle("Title", parent=BODY, fontName="LogSans-Bold", fontSize=21,
                    leading=25, spaceAfter=8)
H2 = ParagraphStyle("Week", parent=BODY, fontName="LogSans-Bold", fontSize=16,
                    leading=19, spaceAfter=5)
H3 = ParagraphStyle("Label", parent=BODY, fontName="LogSans-Bold", fontSize=11,
                    leading=14, spaceBefore=8, spaceAfter=4)


def paragraph(text, style=BODY):
    return Paragraph(escape(text), style)


def period(week):
    a, b = date.fromisoformat(week["start"]), date.fromisoformat(week["end"])
    if a.month == b.month:
        return f"{a.day:02d} to {b.day:02d} {b:%B %Y}"
    return f"{a:%d %B} to {b:%d %B %Y}"


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("LogSans", 8)
    canvas.setFillColor(colors.HexColor("#555555"))
    canvas.drawString(54, 30, "IT23203280   |   C2 Research Logbook   |   Compiled 20 October 2026")
    canvas.drawRightString(letter[0]-54, 30, f"{doc.page} / 12")
    canvas.restoreState()


def write_pdf():
    story = []
    for index, week in enumerate(DATA["weeks"]):
        if index:
            story.append(PageBreak())
        if index == 0:
            story += [paragraph(DATA["title"], H1),
                paragraph("Audio to synthesizer parameter estimation and reliability calibration"),
                paragraph("Student name ____________________________    Student ID IT23203280", SMALL),
                paragraph("Record period 03 August to 20 October 2026    Compiled 20 October 2026", SMALL),
                paragraph("Entries group related work by date. Weekly review comments and signatures are completed by the reviewer using the actual signing date.", SMALL),
                Spacer(1, 10)]
        story += [paragraph(f"Week {week['number']}   {period(week)}", H2),
                  paragraph(week["focus"]), Spacer(1, 6)]
        rows = [[paragraph("Date", DATE), paragraph("Work completed and result", DATE)]]
        for when, work, result in week["entries"]:
            rows.append([paragraph(when, DATE), Paragraph(
                escape(work) + "<br/><b>Result</b> " + escape(result), CELL)])
        table = Table(rows, colWidths=[77, 427], repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), .5, colors.HexColor("#D9D9D9")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ECECEC")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story += [table, Spacer(1, 10), paragraph("Weekly outcome", H3),
                  paragraph(week["outcome"]), paragraph("Next step", H3), paragraph(week["next"]),
                  paragraph("Weekly review", H3),
                  paragraph("Reviewer comments", SMALL),
                  paragraph("________________________________________________________________________", SMALL),
                  paragraph("________________________________________________________________________", SMALL),
                  Spacer(1, 6),
                  paragraph("Reviewed by __________________________    Role  Supervisor / Co supervisor", SMALL),
                  Spacer(1, 9),
                  paragraph("Signature ____________________________    Date actually signed ____ / ____ / ______", SMALL)]
    PDF.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(PDF), pagesize=letter, rightMargin=54, leftMargin=54,
        topMargin=42, bottomMargin=48, title=DATA["title"], author="IT23203280",
        subject="Weekly C2 research record from 3 August to 20 October 2026")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def write_markdown():
    lines = ["# " + DATA["title"], "",
        "Audio to synthesizer parameter estimation and reliability calibration", "",
        "Student name: ____________________________", "Student ID: IT23203280", "",
        "Record period: 03 August to 20 October 2026", "Compiled: 20 October 2026", "",
        "Entries group related work by date. Weekly review comments and signatures are completed by the reviewer using the actual signing date.", ""]
    for week in DATA["weeks"]:
        lines += [f"## Week {week['number']}   {period(week)}", "", week["focus"], ""]
        for when, work, result in week["entries"]:
            lines += [f"### {when}", "", work, "", "Result: " + result, ""]
        lines += ["### Weekly outcome", "", week["outcome"], "", "### Next step", "", week["next"], "",
            "### Weekly review", "", "Reviewer comments: ____________________________________________", "",
            "_____________________________________________________________", "",
            "Reviewed by: __________________    Role: Supervisor / Co supervisor", "",
            "Signature: ____________________    Date actually signed: ____ / ____ / ______", "", "---", ""]
    MD.write_text("\n".join(lines), encoding="utf-8")


def verify():
    reader = PdfReader(PDF)
    assert len(reader.pages) == 12, f"Expected one page per week; got {len(reader.pages)}"
    for index, page in enumerate(reader.pages, 1):
        text = page.extract_text()
        assert f"Week {index}" in text, f"Week {index} starts on the wrong page"
        assert "Date actually signed" in text, f"Missing review block on page {index}"
        assert "Signature" in text and "Reviewer comments" in text
    combined = "\n".join(p.extract_text() for p in reader.pages)
    for forbidden in ("C1", "C3", "C4", "viva", "tomorrow"):
        assert forbidden not in combined, forbidden
    assert "0.115385" in combined and "0.126112" in combined
    report = {"pages": 12, "weekly_review_blocks": 12,
        "entries": sum(len(w["entries"]) for w in DATA["weeks"]),
        "pdf": str(PDF), "editable_text": str(MD),
        "record_period_end": DATA["period_end"], "date_review_note": DATA["date_review_note"]}
    (HERE / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    write_markdown()
    write_pdf()
    verify()
