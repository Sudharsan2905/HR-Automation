import asyncio
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from app._core.settings import settings
from app.components.utils.logger import log


class EmailClient:
    """SMTP email sender."""

    def __init__(self, host: str, port: int, user: str, password: str, from_name: str, from_address: str = ""):
        self.from_address = from_address or user
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.from_name = from_name

    def _send(self, to: str, subject: str, html_body: str, attachments: list[str] | None = None, cc: str | None = None):
        msg = MIMEMultipart("mixed")
        msg["From"] = f"{self.from_name} <{self.from_address}>"
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc
        msg.attach(MIMEText(html_body, "html"))

        for filepath in (attachments or []):
            p = Path(filepath)
            if p.exists():
                with open(p, "rb") as f:
                    part = MIMEApplication(f.read(), Name=p.name)
                part["Content-Disposition"] = f'attachment; filename="{p.name}"'
                msg.attach(part)

        with smtplib.SMTP(self.host, self.port) as server:
            server.starttls()
            server.login(self.user, self.password)
            server.send_message(msg)

        log.info("Email sent to %s: %s", to, subject)

    async def send_html(self, to: str, subject: str, html_body: str, cc: str | None = None, attachments: list[str] | None = None) -> bool:
        """Send an arbitrary HTML email; returns False (and logs) instead of raising."""
        try:
            await asyncio.to_thread(self._send, to, subject, html_body, attachments, cc)
            return True
        except Exception as e:
            log.warning("Email to %s failed: %s: %s", to, type(e).__name__, e)
            return False


_instance: EmailClient | None = None


def init_email_client():
    """Initialize SMTP email singleton."""
    global _instance
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        log.warning("SMTP not configured — emails will be skipped")
        return
    _instance = EmailClient(
        host=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        user=settings.SMTP_USER,
        password=settings.SMTP_PASSWORD,
        from_name=settings.SMTP_FROM_NAME,
        from_address=settings.SMTP_FROM,
    )
    log.info("Email client initialized")


def get_email_client() -> EmailClient | None:
    """Get the email singleton (None if not configured)."""
    return _instance
