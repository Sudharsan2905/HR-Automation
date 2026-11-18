import base64
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app._core.settings import settings
from app.components.utils.logger import log

_template_dir = Path(__file__).parent / "templates"
_jinja_env = Environment(loader=FileSystemLoader(str(_template_dir)), autoescape=True)

# Pre-load logo as base64 at module level
_logo_path = _template_dir / "softsuave_logo.webp"
_logo_b64 = ""
if _logo_path.exists():
    _logo_b64 = base64.b64encode(_logo_path.read_bytes()).decode()

# Register Tamil font for ReportLab (done once at module level)
_tamil_font_registered = False
def _ensure_tamil_font():
    global _tamil_font_registered
    if _tamil_font_registered:
        return
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        font_path = _template_dir / "NotoSansTamil-Regular.ttf"
        if font_path.exists():
            pdfmetrics.registerFont(TTFont("Tamil", str(font_path)))
            from reportlab.lib.fonts import addMapping
            addMapping("Tamil", 0, 0, "Tamil")
            addMapping("Tamil", 1, 0, "Tamil")
            addMapping("Tamil", 0, 1, "Tamil")
            addMapping("Tamil", 1, 1, "Tamil")
            _tamil_font_registered = True
        else:
            log.warning("Tamil font not found at %s — Tamil text will use Helvetica fallback", font_path)
    except Exception as e:
        log.warning("Tamil font registration failed: %s", e)

# Tamil Unicode block: U+0B80–U+0BFF
def _mixed_html(text: str) -> str:
    """Wrap Tamil and Latin segments in per-font XML tags for ReportLab.
    Falls back to Helvetica for all text when the Tamil font is not registered."""
    if not text:
        return ""
    escaped_all = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if not _tamil_font_registered:
        return f'<font name="Helvetica">{escaped_all}</font>'
    segments: list[tuple[str, bool]] = []
    buf, cur_tamil = "", None
    for ch in text:
        t = "஀" <= ch <= "௿"
        if cur_tamil is None:
            cur_tamil = t
        if t != cur_tamil:
            segments.append((buf, cur_tamil))
            buf, cur_tamil = "", t
        buf += ch
    if buf:
        segments.append((buf, cur_tamil if cur_tamil is not None else False))
    parts = []
    for seg, is_tamil in segments:
        seg = seg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        font = "Tamil" if is_tamil else "Helvetica"
        parts.append(f'<font name="{font}">{seg}</font>')
    return "".join(parts)


def _interview_dir(interview_id: str) -> Path:
    """Return reports/{interview_id}/ directory, creating it if needed."""
    d = Path(settings.REPORT_STORAGE_PATH) / interview_id
    d.mkdir(parents=True, exist_ok=True)
    return d


async def generate_report_pdf(evaluation, question_set) -> str:
    """Generate suvera_insights.pdf from evaluation result — returns file path."""
    pdf_path = str(_interview_dir(evaluation.interview_id) / "suvera_insights.pdf")

    html_content = _jinja_env.get_template("report.html").render(
        app_name=settings.APP_NAME,
        candidate_name=evaluation.candidate_name,
        interview_date=evaluation.evaluated_at.strftime("%B %d, %Y"),
        difficulty_level=question_set.difficulty_level.value.title(),
        domain=question_set.domain.replace("_", " ").title(),
        domain_title=question_set.domain_title.replace("_", " ").title(),
        tags=question_set.tags,
        total_score=evaluation.total_score,
        max_score=evaluation.max_score,
        percentage=evaluation.percentage,
        overall_feedback=evaluation.overall_feedback,
        strengths=evaluation.strengths,
        areas_for_improvement=evaluation.areas_for_improvement,
        evaluated_results=evaluation.evaluated_results,
        logo_b64=_logo_b64,
    )

    try:
        _generate_with_weasyprint(html_content, pdf_path)
    except ImportError:
        _generate_with_reportlab(evaluation, question_set, pdf_path)

    log.info("PDF report generated: %s", pdf_path)
    return pdf_path


async def generate_conversation_pdf(interview_id: str, candidate_name: str, interview_date: str, domain: str, domain_title: str, transcripts: list) -> str:
    """Generate raw_conversation.pdf from transcripts — returns file path."""
    pdf_path = str(_interview_dir(interview_id) / "raw_conversation.pdf")

    role_labels = {"ai": "Suvera AI", "candidate": "Candidate", "interviewer": "Panel"}
    messages = []
    for t in transcripts:
        messages.append({
            "role": t.role,
            "role_label": role_labels.get(t.role, t.role),
            "timestamp": t.timestamp.strftime("%H:%M:%S"),
            "text": t.text,
        })

    html_content = _jinja_env.get_template("raw_conversation.html").render(
        app_name=settings.APP_NAME,
        candidate_name=candidate_name,
        interview_date=interview_date,
        domain=domain.replace("_", " ").title(),
        domain_title=domain_title.replace("_", " ").title(),
        total_messages=len(messages),
        messages=messages,
        logo_b64=_logo_b64,
    )

    try:
        _generate_with_weasyprint(html_content, pdf_path)
    except ImportError:
        _generate_conversation_with_reportlab(messages, candidate_name, interview_date, domain, domain_title, pdf_path)

    log.info("Conversation PDF generated: %s", pdf_path)
    return pdf_path


def _generate_with_weasyprint(html_content: str, pdf_path: str):
    """Generate PDF from HTML using WeasyPrint."""
    from weasyprint import HTML
    HTML(string=html_content, base_url=str(_template_dir)).write_pdf(pdf_path)


def _generate_with_reportlab(evaluation, question_set, pdf_path: str):
    """Fallback PDF generation using ReportLab."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    doc = SimpleDocTemplate(pdf_path, pagesize=A4, topMargin=0.5 * inch, bottomMargin=0.5 * inch)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle("Title", parent=styles["Title"], fontSize=18, spaceAfter=4)
    elements.append(Paragraph("SkillMate — Interview Report", title_style))
    sub_style = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=9, textColor=colors.grey, alignment=1)
    elements.append(Paragraph("Product by Softsuave AI team", sub_style))
    elements.append(Spacer(1, 16))

    domain_label = question_set.domain.replace("_", " ").title()
    domain_title = question_set.domain_title.replace("_", " ").title()
    info_data = [
        ["Candidate", evaluation.candidate_name],
        ["Date", evaluation.evaluated_at.strftime("%B %d, %Y")],
        ["Domain", f"{domain_label} / {domain_title}"],
        ["Difficulty", question_set.difficulty_level.value.title()],
        ["Tags", ", ".join(question_set.tags)],
    ]
    info_table = Table(info_data, colWidths=[1.5 * inch, 4.5 * inch])
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.Color(0.9, 0.93, 0.96)),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 16))

    score_style = ParagraphStyle("Score", parent=styles["Heading2"], fontSize=14)
    elements.append(Paragraph(
        f"Score: {evaluation.total_score:.1f} / {evaluation.max_score:.0f} "
        f"({evaluation.percentage:.1f}%)",
        score_style,
    ))
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("Overall Feedback", styles["Heading3"]))
    elements.append(Paragraph(evaluation.overall_feedback, styles["Normal"]))
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("Strengths", styles["Heading3"]))
    for s in evaluation.strengths:
        elements.append(Paragraph(f"• {s}", styles["Normal"]))
    elements.append(Spacer(1, 8))

    elements.append(Paragraph("Areas for Improvement", styles["Heading3"]))
    for imp in evaluation.areas_for_improvement:
        elements.append(Paragraph(f"• {imp}", styles["Normal"]))
    elements.append(Spacer(1, 16))

    elements.append(Paragraph("Detailed Question Breakdown", styles["Heading2"]))
    elements.append(Spacer(1, 8))

    body_style = ParagraphStyle("Body", parent=styles["Normal"], fontSize=9, leading=12)
    for i, qe in enumerate(evaluation.evaluated_results):
        asked_label = "AI" if qe.asked_by == "ai" else "Panel"
        elements.append(Paragraph(f"Q{i+1}. {qe.question} <i>(asked by {asked_label})</i>", styles["Heading4"]))
        elements.append(Paragraph(f"<b>Answer:</b> {qe.answer}", body_style))
        elements.append(Paragraph(f"<b>Score:</b> {qe.score}/10", body_style))
        elements.append(Paragraph(f"<b>Feedback:</b> {qe.feedback}", body_style))
        elements.append(Spacer(1, 10))

    doc.build(elements)


def _generate_conversation_with_reportlab(messages: list, candidate_name: str, interview_date: str, domain: str, domain_title: str, pdf_path: str):
    """Fallback conversation PDF generation using ReportLab with Tamil font support."""
    _ensure_tamil_font()

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    doc = SimpleDocTemplate(pdf_path, pagesize=A4, topMargin=0.5 * inch, bottomMargin=0.5 * inch)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle("Title", parent=styles["Title"], fontSize=18, spaceAfter=4)
    elements.append(Paragraph("SkillMate — Interview Transcript", title_style))
    sub_style = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=9, textColor=colors.grey, alignment=1)
    elements.append(Paragraph("Product by Softsuave AI team", sub_style))
    elements.append(Spacer(1, 16))

    info_data = [
        ["Candidate", candidate_name],
        ["Date", interview_date],
        ["Domain", f"{domain.replace('_', ' ').title()} / {domain_title.replace('_', ' ').title()}"],
        ["Total Messages", str(len(messages))],
    ]
    info_table = Table(info_data, colWidths=[1.5 * inch, 4.5 * inch])
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.Color(0.9, 0.93, 0.96)),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 16))

    role_colors = {
        "ai": colors.Color(0.16, 0.50, 0.73),
        "candidate": colors.Color(0.15, 0.68, 0.38),
        "interviewer": colors.Color(0.49, 0.23, 0.93),
        "panel": colors.Color(0.49, 0.23, 0.93),
    }
    msg_style = ParagraphStyle("Msg", fontName="Helvetica", fontSize=11, leading=17)

    for msg in messages:
        role_color = role_colors.get(msg["role"], colors.black)
        rc = role_color
        hex_c = "#{:02x}{:02x}{:02x}".format(int(rc.red * 255), int(rc.green * 255), int(rc.blue * 255))
        label_style = ParagraphStyle("Label", fontName="Helvetica", fontSize=9, textColor=colors.grey)
        label_html = f'<font name="Helvetica-Bold" color="{hex_c}">{msg["role_label"]}</font> · {msg["timestamp"]}'
        elements.append(Paragraph(label_html, label_style))
        elements.append(Paragraph(_mixed_html(msg["text"]), msg_style))
        elements.append(Spacer(1, 8))

    doc.build(elements)
