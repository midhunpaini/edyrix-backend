import asyncio
import functools
from html import escape

import resend

from app.config import settings


def _send_sync(to: str, subject: str, html: str) -> bool:
    """Blocking Resend API call — run via executor, never call directly in async code."""
    resend.api_key = settings.RESEND_API_KEY
    resend.Emails.send(
        {
            "from": settings.FROM_EMAIL,
            "to": [to],
            "subject": subject,
            "html": html,
        }
    )
    return True


async def send_email(to: str, subject: str, html: str) -> bool:
    """Send a transactional email via Resend without blocking the event loop."""
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, functools.partial(_send_sync, to, subject, html)
        )
    except Exception:
        return False


async def send_doubt_answered_email(
    to: str, question_text: str, answer_text: str
) -> bool:
    """Notify a student by email that their doubt has been answered."""
    safe_q = escape(question_text)
    safe_a = escape(answer_text)
    html = f"""
    <div style="font-family: 'DM Sans', sans-serif; max-width: 600px; margin: auto;">
      <h2 style="color: #0D6E6E;">Your doubt has been answered!</h2>
      <p><strong>Your question:</strong></p>
      <blockquote style="border-left: 3px solid #0D6E6E; padding-left: 12px; color: #555;">
        {safe_q}
      </blockquote>
      <p><strong>Answer:</strong></p>
      <p>{safe_a}</p>
      <hr />
      <p style="color: #999; font-size: 12px;">Edyrix — Kerala SCERT Study Platform</p>
    </div>
    """
    return await send_email(to, "Your doubt has been answered — Edyrix", html)
