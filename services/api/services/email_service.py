import os
import logging

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "Shadow Pages <noreply@shadowpages.com>")
APP_URL = os.getenv("APP_URL", "http://localhost:8080")


async def send_email(to: str, subject: str, html: str) -> bool:
    """Send an email via Resend API. Returns True on success, False otherwise."""
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not set — skipping email to %s: %s", to, subject)
        return False
    try:
        import resend

        resend.api_key = RESEND_API_KEY
        resend.Emails.send(
            {
                "from": EMAIL_FROM,
                "to": [to],
                "subject": subject,
                "html": html,
            }
        )
        logger.info("Email sent to %s: %s", to, subject)
        return True
    except Exception as e:
        logger.error("Failed to send email to %s: %s", to, e)
        return False
