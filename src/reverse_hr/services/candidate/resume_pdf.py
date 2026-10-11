"""PDF guest implementation. Never imported by Candidate for parsing untrusted files."""

import io
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

from reverse_hr.contracts.resume_contracts import ExtractedPDF, PDFData

OCR_LANGUAGES = "eng+rus"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def extract(raw):
    from pypdf import PdfReader

    if not raw.startswith(b"%PDF-"):
        raise ValueError("Invalid PDF")
    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 10:
        raise ValueError("Unsupported PDF")
    # No attachments, interactive forms, scripts or automatic actions are admitted.
    forbidden = {
        "/JavaScript",
        "/JS",
        "/Launch",
        "/EmbeddedFiles",
        "/OpenAction",
        "/AA",
        "/XFA",
        "/AcroForm",
    }
    visited = set()

    def inspect(value, depth=0):
        if depth > 40:
            raise ValueError("PDF nesting")
        if hasattr(value, "idnum"):
            key = (value.idnum, value.generation)
            if key in visited:
                return
            visited.add(key)
            value = value.get_object()
        if isinstance(value, dict):
            if forbidden & set(value):
                raise ValueError("Active PDF")
            for child in value.values():
                inspect(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                inspect(child, depth + 1)

    inspect(reader.trailer)
    texts, scanned = [], []
    with tempfile.TemporaryDirectory(prefix="pdf-") as directory:
        source = Path(directory) / "input.pdf"
        source.write_bytes(raw)
        for index, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            if len(re.sub(r"\s", "", text)) < 20:
                if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
                    raise RuntimeError("OCR unavailable")
                prefix = str(Path(directory) / "page")
                subprocess.run(
                    [
                        "pdftoppm",
                        "-f",
                        str(index),
                        "-l",
                        str(index),
                        "-singlefile",
                        "-scale-to",
                        "1800",
                        "-png",
                        str(source),
                        prefix,
                    ],
                    check=True,
                    timeout=12,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                result = subprocess.run(
                    ["tesseract", prefix + ".png", "stdout", "-l", OCR_LANGUAGES],
                    check=True,
                    timeout=12,
                    capture_output=True,
                    env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"},
                )
                text = result.stdout.decode("utf-8")
                scanned.append(index)
                Path(prefix + ".png").unlink(missing_ok=True)
            texts.append(text)
            if sum(map(len, texts)) > 40000:
                raise ValueError("PDF text too large")
    text = "\n".join(texts)
    if not text.strip():
        raise ValueError("Empty PDF")
    return ExtractedPDF(text=text, pages=len(reader.pages), ocr_pages=scanned)


def render(data):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    data = PDFData.model_validate(data)
    pdfmetrics.registerFont(TTFont("ResumeUnicode", FONT))
    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=44,
        leftMargin=44,
        topMargin=42,
        bottomMargin=44,
        title="Resume",
        author="",
        creator="Reverse HR",
    )
    body = ParagraphStyle(
        "body",
        fontName="ResumeUnicode",
        fontSize=10,
        leading=15,
        spaceAfter=9,
        textColor=colors.HexColor("#24354b"),
        splitLongWords=True,
    )
    heading = ParagraphStyle(
        "heading",
        parent=body,
        fontSize=13,
        leading=19,
        spaceBefore=14,
        textColor=colors.HexColor("#176882"),
    )
    title = ParagraphStyle("title", parent=body, fontSize=22, leading=28, spaceAfter=16)
    story = []

    def paragraph(text, style=body):
        story.append(Paragraph(escape(str(text)).replace("\n", "<br/>"), style))

    paragraph(data.name, title)
    paragraph(data.specialization, heading)
    paragraph("Демонстрационный режим / Demo assessment")
    paragraph(
        "Подтверждённая оценка / Verified grade: "
        + (data.confirmed_grade.value if data.confirmed_grade else "нет / not available")
    )
    paragraph("Самоописание / Declared grade: " + data.declared_grade.value)
    for item in data.specializations:
        if item.specialization == data.specialization:
            continue
        paragraph(item.specialization, heading)
        paragraph("Подтверждённый уровень: " + (item.confirmed_grade or "не подтверждён"))
        paragraph("Заявленный уровень: " + item.declared_grade)
    paragraph("Заявленные навыки / Declared skills: " + ", ".join(data.declared_skills))
    if data.variant == "full":
        paragraph("Контакты / Contacts", heading)
        paragraph(data.email or "Не указаны / Not provided")
        if data.phone:
            paragraph(data.phone)
    else:
        paragraph("Обезличенное резюме. Контакты закрыты. / Anonymous resume.")
    for label, values in (
        ("О себе / Summary", [data.summary] if data.summary else []),
        ("Опыт / Experience", data.experience),
        ("Образование / Education", data.education),
    ):
        if values:
            paragraph(label, heading)
            for value in values:
                paragraph(value)
    if data.achievements:
        paragraph("Подтверждённые достижения / Verified achievements", heading)
        for item in data.achievements:
            paragraph(item.event, heading)
            paragraph(item.discipline + " | " + item.format + " | " + str(item.occurred_on))
            details = []
            if item.place is not None:
                details.append("Место / Place: " + str(item.place))
            if item.points is not None:
                details.append("Баллы / Points: " + str(item.points))
            if details:
                paragraph("; ".join(details))
            paragraph("Источник / Source: " + item.source_name)
            paragraph("Проверено / Checked: " + item.checked_at.date().isoformat())
            if item.demo:
                paragraph("ДЕМОНСТРАЦИОННОЕ ДОСТИЖЕНИЕ / DEMO ACHIEVEMENT")
    story.append(Spacer(1, 10))
    paragraph(
        "Опыт и навыки указаны кандидатом. Подтверждённый грейд хранится отдельно. / "
        "Experience and skills are candidate declarations."
    )

    def footer(canvas, document):
        canvas.setFont("ResumeUnicode", 8)
        canvas.drawRightString(A4[0] - 44, 24, str(document.page))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    raw = output.getvalue()
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("PDF output too large")
    return raw
