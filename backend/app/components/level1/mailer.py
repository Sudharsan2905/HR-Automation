"""Email delivery through SkillMate's SMTP client (mock-logged when SMTP is not configured)."""

from app.components.utils.email_client import get_email_client
from app.components.utils.logger import log

last_error: str = ""


async def send_email(to: str, subject: str, html: str) -> bool:
    """Send an HTML email; True on success or when SMTP is unconfigured."""
    global last_error
    client = get_email_client()
    if client is None:
        log.info("[Email Mock] To: %s | Subject: %s", to, subject)
        return True
    ok = await client.send_html(to, subject, html)
    if not ok:
        last_error = f"SMTP delivery to {to} failed"
    return ok
