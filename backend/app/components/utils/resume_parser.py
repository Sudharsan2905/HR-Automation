import io

from fastapi import UploadFile

from app.components.utils.logger import log


async def parse_resume(file: UploadFile) -> str:
    """Extract text from uploaded resume (PDF or DOCX)."""
    content = await file.read()
    filename = (file.filename or "").lower()

    if filename.endswith(".pdf"):
        return _extract_pdf(content)
    elif filename.endswith(".docx"):
        return _extract_docx(content)
    else:
        raise ValueError(f"Unsupported file type: {filename}. Use PDF or DOCX.")


def _extract_pdf(content: bytes) -> str:
    """Extract text from PDF bytes using PyMuPDF."""
    import fitz

    doc = fitz.open(stream=content, filetype="pdf")
    text = "\n".join(page.get_text() for page in doc)
    doc.close()
    log.info("PDF parsed: %d characters", len(text))
    return text


def _extract_docx(content: bytes) -> str:
    """Extract text from DOCX bytes."""
    from docx import Document

    doc = Document(io.BytesIO(content))
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    log.info("DOCX parsed: %d characters", len(text))
    return text
