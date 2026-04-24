import resend

from app.config import settings


def send_email(to: str, subject: str, html: str) -> bool:
    try:
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
    except Exception:
        return False


def send_doubt_answered_email(to: str, question_text: str, answer_text: str) -> bool:
    html = f"""
    <div style="font-family: 'DM Sans', sans-serif; max-width: 600px; margin: auto;">
      <h2 style="color: #0D6E6E;">Your doubt has been answered!</h2>
      <p><strong>Your question:</strong></p>
      <blockquote style="border-left: 3px solid #0D6E6E; padding-left: 12px; color: #555;">
        {question_text}
      </blockquote>
      <p><strong>Answer:</strong></p>
      <p>{answer_text}</p>
      <hr />
      <p style="color: #999; font-size: 12px;">Edyrix — Kerala SCERT Study Platform</p>
    </div>
    """
    return send_email(to, "Your doubt has been answered — Edyrix", html)
