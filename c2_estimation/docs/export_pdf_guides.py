"""Export C2 Markdown guides as readable, bookmarked local PDFs.

Uses the bundled document runtime (ReportLab/Pillow/pdfplumber/pypdf), not the
frozen synthesis environment. Source guides, research code and data are read only.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import subprocess
import textwrap
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader
import pdfplumber
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Flowable, Frame, Paragraph, PageTemplate, Spacer, Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "output/pdf"
PREVIEW = ROOT / "tmp/pdfs/c2_guides"
FILES = ("COMPONENT_STUDY_GUIDE", "DEMONSTRATION_WALKTHROUGH", "METRICS_REFERENCE",
         "DEMONSTRATION_WALKTHROUGH_EXPLAINED")
TEAL = colors.HexColor("#17645F")
INK = colors.HexColor("#203039")
MUTED = colors.HexColor("#52636B")
LINE = colors.HexColor("#D9E2E4")
PALE = colors.HexColor("#F3F6F7")


def register_fonts():
    for name, filename in (
        ("C2Sans", "calibri.ttf"), ("C2Sans-Bold", "calibrib.ttf"),
        ("C2Sans-Italic", "calibrii.ttf"), ("C2Sans-BoldItalic", "calibriz.ttf"),
        ("C2Mono", "consola.ttf"), ("C2Mono-Bold", "consolab.ttf"),
    ):
        pdfmetrics.registerFont(TTFont(name, str(Path("C:/Windows/Fonts") / filename)))
    pdfmetrics.registerFontFamily("C2Sans", normal="C2Sans", bold="C2Sans-Bold",
                                  italic="C2Sans-Italic", boldItalic="C2Sans-BoldItalic")


def printable(text):
    return text.translate(str.maketrans({
        "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",
        "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
        "\u00a0": " ", "\u2192": "->", "\u2190": "<-",
    }))


def slug(text):
    text = re.sub(r"[^\w\s-]", "", text.lower(), flags=re.UNICODE)
    return re.sub(r"\s", "-", text)


def destination(target):
    target = target.strip("<>")
    if target.startswith(("#", "http://", "https://")):
        return target
    filename = target.split("#", 1)[0].replace("\\", "/").rsplit("/", 1)[-1]
    if filename.removesuffix(".md") in FILES:
        return filename.removesuffix(".md") + ".pdf"
    if re.match(r"^[A-Za-z]:[/\\]", target):
        target = re.sub(r":\d+$", "", target).replace("\\", "/")
        return "file:///" + quote(target, safe="/:#")
    return target


TOKEN = re.compile(r"(\[[^\]]+\]\((?:<[^>]+>|[^)\n]+)\)|`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)")
LINK = re.compile(r"\[([^\]]+)\]\((<[^>]+>|[^)\n]+)\)")


def inline(text):
    pieces, offset = [], 0
    for match in TOKEN.finditer(text):
        pieces.append(html.escape(printable(text[offset:match.start()])))
        token = match.group()
        link = LINK.fullmatch(token)
        if link:
            pieces.append('<link href="' + html.escape(destination(link[2]), quote=True)
                          + '" color="#17645F">' + inline(link[1]) + '</link>')
        elif token.startswith("`"):
            pieces.append('<font name="C2Mono" size="8.3">' + html.escape(printable(token[1:-1])) + '</font>')
        elif token.startswith("**"):
            pieces.append("<b>" + html.escape(printable(token[2:-2])) + "</b>")
        else:
            pieces.append("<i>" + html.escape(printable(token[1:-1])) + "</i>")
        offset = match.end()
    pieces.append(html.escape(printable(text[offset:])))
    return "".join(pieces)


class CodeBlock(Flowable):
    """Monospaced code with measured wrapping and page-safe line splitting."""
    def __init__(self, source, wrapped=False):
        Flowable.__init__(self)
        self.source = source if isinstance(source, list) else source.splitlines()
        self.wrapped = wrapped
        self.lines = None
        self.font_size = 8
        self.leading = 10.4
        self.spaceAfter = 9
        self.spaceBefore = 3

    def wrap(self, available_width, available_height):
        self.width = available_width
        if self.lines is None:
            if self.wrapped:
                self.lines = self.source
            else:
                limit = max(30, int((available_width - 22) / pdfmetrics.stringWidth("M", "C2Mono", self.font_size)))
                self.lines = []
                for raw in self.source:
                    line = printable(raw.expandtabs(4))
                    if len(line) <= limit:
                        self.lines.append(line)
                    else:
                        indent = min(len(line) - len(line.lstrip()) + 4, limit // 3)
                        self.lines.extend(textwrap.wrap(line, width=limit, subsequent_indent=" " * indent,
                            replace_whitespace=False, drop_whitespace=True, break_long_words=True,
                            break_on_hyphens=False) or [""])
        self.height = len(self.lines) * self.leading + 18
        return self.width, self.height

    def split(self, available_width, available_height):
        self.wrap(available_width, available_height)
        count = int((available_height - 18) / self.leading)
        if count < 2:
            return []
        return [CodeBlock(self.lines[:count], wrapped=True), CodeBlock(self.lines[count:], wrapped=True)]

    def draw(self):
        canvas = self.canv
        canvas.setFillColor(PALE)
        canvas.setStrokeColor(LINE)
        canvas.roundRect(0, 0, self.width, self.height, 4, fill=1, stroke=1)
        canvas.setFont("C2Mono", self.font_size)
        canvas.setFillColor(INK)
        for number, line in enumerate(self.lines):
            if pdfmetrics.stringWidth(line, "C2Mono", self.font_size) > self.width - 20 + .1:
                raise ValueError("Code wrapping exceeded the frame")
            canvas.drawString(10, self.height - 12 - self.font_size - number * self.leading, line)


class GuideDoc(BaseDocTemplate):
    def __init__(self, output, wide, short_title):
        page_size = landscape(A4) if wide else A4
        super().__init__(str(output), pagesize=page_size, leftMargin=43, rightMargin=43,
                         topMargin=48, bottomMargin=44, title=short_title,
                         author="C2 research", pageCompression=1)
        self.short_title = short_title
        self.header_sections = []
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height,
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates(PageTemplate(id="guide", frames=frame, onPage=self.page_decoration))
        self.outline_level = -1

    def page_decoration(self, canvas, doc):
        width, height = self.pagesize
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.line(43, height - 32, width - 43, height - 32)
        canvas.setFont("C2Sans-Bold", 8)
        canvas.setFillColor(TEAL)
        canvas.drawString(43, height - 23, self.short_title.upper())
        canvas.setFont("C2Sans", 8)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(width - 43, 25, str(doc.page))
        canvas.drawString(43, 25, "C2 | Study and demonstration guides | 15 October 2026")
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if getattr(flowable, "guide_anchor", None):
            self.canv.bookmarkPage(flowable.guide_anchor)
            level = min(flowable.guide_level - 1, self.outline_level + 1)
            self.canv.addOutlineEntry(flowable.guide_title, flowable.guide_anchor, level=level, closed=False)
            self.outline_level = level
            self.header_sections.append({"title": flowable.guide_title, "anchor": flowable.guide_anchor, "page": self.page})


def styles():
    body = ParagraphStyle("Body", fontName="C2Sans", fontSize=10.2, leading=14.2,
                          textColor=INK, spaceAfter=7, splitLongWords=True, allowWidows=0, allowOrphans=0)
    result = {"body": body}
    for level, size in ((1, 25), (2, 17), (3, 13), (4, 11)):
        result[f"h{level}"] = ParagraphStyle(f"H{level}", parent=body,
            fontName="C2Sans-Bold", fontSize=size, leading=size*1.2,
            textColor=TEAL if level <= 2 else INK,
            spaceBefore=16 if level > 1 else 6, spaceAfter=8, keepWithNext=True)
    result["quote"] = ParagraphStyle("Quote", parent=body, leftIndent=12, rightIndent=8,
                                    textColor=MUTED, spaceBefore=3, spaceAfter=9)
    result["list"] = ParagraphStyle("List", parent=body, leftIndent=16, bulletIndent=0, spaceAfter=5)
    result["cell"] = ParagraphStyle("Cell", parent=body, fontSize=8.5, leading=11.2, spaceAfter=0, allowWidows=1, allowOrphans=1)
    result["header"] = ParagraphStyle("TableHeader", parent=result["cell"], fontName="C2Sans-Bold", textColor=TEAL)
    return result


def is_table(line):
    return line.strip().startswith("|") and line.strip().endswith("|")


def make_table(lines, width, sheet):
    rows = []
    for line in lines:
        cells = [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line.strip()[1:-1])]
        if all(re.fullmatch(r":?-+:?", c) for c in cells):
            continue
        rows.append(cells)
    columns = len(rows[0])
    if not all(len(r) == columns for r in rows):
        raise ValueError("Irregular Markdown table")
    if columns >= 5:
        widths = [width*.25] + [width*.75/(columns-1)]*(columns-1)
    elif columns == 3:
        widths = [width*.26, width*.31, width*.43]
    elif columns == 2:
        widths = [width*.37, width*.63]
    else:
        widths = [width/columns]*columns
    rendered = [[Paragraph(inline(c), sheet["header"] if r == 0 else sheet["cell"]) for c in row]
                for r, row in enumerate(rows)]
    table = Table(rendered, colWidths=widths, repeatRows=1, hAlign="LEFT", splitByRow=1,
                  spaceBefore=4, spaceAfter=12)
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E7F0EE")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFBFC")]),
        ("LINEBELOW", (0, 0), (-1, 0), .7, colors.HexColor("#A9C8C2")),
        ("LINEBELOW", (0, 1), (-1, -1), .35, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def special(line):
    return bool(re.match(r"^(#{1,6}\s|```|>\s?|\s*(?:[-*]|\d+\.)\s+)", line)) or is_table(line)


def flowables(source, document):
    lines, sheet, out = source.splitlines(), styles(), []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("<!--"):
            raise ValueError("Remove visible navigation comments from source before export")
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            level, text = len(heading[1]), heading[2]
            p = Paragraph(inline(text), sheet[f"h{min(level,4)}"])
            p.guide_anchor, p.guide_title, p.guide_level = slug(text), printable(text), level
            out.append(p)
            if level == 1:
                out.append(Paragraph("Printable edition. Use the Contents links or PDF bookmarks to navigate. "
                    "Long code lines wrap for printing; copy executable commands from the Markdown guide. "
                    "Source-file links refer to the local repository; keep related PDFs together for related-guide links.", sheet["quote"]))
            i += 1
        elif line.startswith("```"):
            code = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            if i == len(lines):
                raise ValueError("Unclosed code fence")
            out.append(CodeBlock("\n".join(code)))
            i += 1
        elif is_table(line):
            block = []
            while i < len(lines) and is_table(lines[i]):
                block.append(lines[i])
                i += 1
            out.append(make_table(block, document.width, sheet))
        elif line.startswith(">"):
            block = []
            while i < len(lines) and lines[i].startswith(">"):
                block.append(re.sub(r"^>\s?", "", lines[i]))
                i += 1
            out.append(Paragraph(inline(" ".join(block)), sheet["quote"]))
        elif re.match(r"^\s*(?:[-*]|\d+\.)\s+", line):
            match = re.match(r"^\s*([-*]|\d+\.)\s+(.+)$", line)
            bullet, block = match[1], [match[2]]
            i += 1
            while i < len(lines) and lines[i].strip() and not special(lines[i]):
                block.append(lines[i].strip())
                i += 1
            out.append(Paragraph(inline(" ".join(block)), sheet["list"], bulletText=bullet))
        else:
            block = [line]
            i += 1
            while i < len(lines) and lines[i].strip() and not special(lines[i]):
                block.append(lines[i])
                i += 1
            out.append(Paragraph(inline(" ".join(block)), sheet["body"]))
    return out


def inspect_pdf(pdf):
    reader = PdfReader(pdf)
    annotations = []
    for page in reader.pages:
        for reference in page.get("/Annots", []):
            annotation = reference.get_object()
            annotations.append(annotation)
    if not reader.outline or not annotations:
        raise ValueError("Expected bookmarks and clickable links")
    outside, bad_text = [], []
    with pdfplumber.open(pdf) as doc:
        for n, page in enumerate(doc.pages, 1):
            for char in page.chars:
                if char.get("text", "").strip() and (char["x0"] < 35 or char["x1"] > page.width-35 or char["top"] < 12 or char["bottom"] > page.height-14):
                    outside.append({"page": n, "text": char["text"]})
            text = page.extract_text() or ""
            if "<!--" in text or "c2-navigation:" in text or "(cid:" in text or "\ufffd" in text:
                bad_text.append(n)
    if outside or bad_text:
        raise ValueError(f"PDF text/geometry issue: {outside[:5]}, bad pages {bad_text}")
    return {"pages": len(reader.pages), "link_annotations": len(annotations),
            "bookmarks_present": True, "text_within_page_bounds": True,
            "navigation_comments_or_missing_glyph_markers": False,
            "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest()}


def render_previews(pdf, poppler):
    folder = PREVIEW / pdf.stem
    folder.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(poppler), "-r", "85", "-png", str(pdf), str(folder/"page")], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    page_count = len(PdfReader(pdf).pages)
    digits = len(str(page_count))
    pages = [folder / f"page-{number:0{digits}d}.png" for number in range(1, page_count+1)]
    if not all(page.is_file() for page in pages):
        raise ValueError(f"Incomplete page rendering: {pdf}")
    font = ImageFont.truetype("C:/Windows/Fonts/calibri.ttf", 16)
    sheets = []
    for start in range(0, len(pages), 6):
        tile_width, tile_height = (420, 320) if "METRICS" in pdf.stem else (300, 445)
        sheet = Image.new("RGB", (tile_width*3, tile_height*2), "#dce2e4")
        draw = ImageDraw.Draw(sheet)
        for offset, page in enumerate(pages[start:start+6]):
            with Image.open(page) as im:
                im = im.convert("RGB")
                im.thumbnail((tile_width-16, tile_height-35), Image.Resampling.LANCZOS)
                x, y = (offset%3)*tile_width+8, (offset//3)*tile_height+26
                sheet.paste(im, (x, y))
                draw.text((x, y-23), f"Page {start+offset+1}", font=font, fill="#203039")
        destination_path = folder / f"contact-{start//6+1:02d}.jpg"
        sheet.save(destination_path, quality=90)
        sheets.append(str(destination_path.relative_to(ROOT)).replace("\\", "/"))
    return {"rendered_pages": len(pages), "contact_sheets": sheets}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--guide", nargs="+", choices=FILES, default=FILES,
                        help="Export only these guides; the default exports all guides")
    args = parser.parse_args()
    register_fonts()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUTPUT / "C2_GUIDES_EXPORT.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"snapshot_date": "2026-10-15", "guides": {}}
    for name in args.guide:
        md = ROOT / "c2_estimation" / (name + ".md")
        output = OUTPUT / (name + ".pdf")
        source = md.read_text(encoding="utf-8")
        short = {"COMPONENT_STUDY_GUIDE": "C2 Component Study Guide",
                 "DEMONSTRATION_WALKTHROUGH": "C2 Demonstration Walkthrough",
                 "METRICS_REFERENCE": "C2 Metrics Reference",
                 "DEMONSTRATION_WALKTHROUGH_EXPLAINED": "C2 Walkthrough with Explanations"}[name]
        document = GuideDoc(output, name == "METRICS_REFERENCE", short)
        document.build(flowables(source, document))
        checked = inspect_pdf(output)
        checked.update(source=str(md.relative_to(ROOT)).replace("\\", "/"),
                       source_sha256=hashlib.sha256(md.read_bytes()).hexdigest(),
                       sections=document.header_sections)
        if args.render:
            poppler = Path("C:/Users/Thithira/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe")
            checked.update(render_previews(output, poppler))
        manifest["guides"][name] = checked
        print(f"{output.name}: {checked['pages']} pages, {checked['link_annotations']} links; geometry/text checks passed", flush=True)
    (OUTPUT / "C2_GUIDES_EXPORT.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
