"""Optional email sender via aiosmtplib.

If SMTP_HOST is not configured the functions return silently.
This keeps the feature opt-in – no env vars required for development.
"""

from __future__ import annotations

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.applications.models import Application
from app.config import Settings

log = logging.getLogger(__name__)


def _settings() -> Settings:
    from app.config import get_settings

    return get_settings()


def _smtp_configured() -> bool:
    s = _settings()
    return bool(getattr(s, "smtp_host", None))


async def send_email(*, to: str, subject: str, html: str) -> None:
    """Send an HTML email. No-op if SMTP is not configured."""
    if not _smtp_configured():
        return

    s = _settings()
    try:
        import aiosmtplib

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = s.smtp_from
        msg["To"] = to
        msg.attach(MIMEText(html, "html", "utf-8"))

        await aiosmtplib.send(
            msg,
            hostname=s.smtp_host,
            port=s.smtp_port,
            username=s.smtp_user or None,
            password=s.smtp_password or None,
            use_tls=s.smtp_tls and s.smtp_port == 465,
            start_tls=s.smtp_tls and s.smtp_port != 465,
        )
        log.debug("Email sent to %s: %s", to, subject)
    except Exception as exc:
        log.warning("Email delivery failed to %s: %s", to, exc)


async def send_password_reset_email(*, email: str, token: str) -> None:
    """Send a password reset link. No-op if SMTP is not configured."""
    if not _smtp_configured():
        log.info("Password reset email skipped: SMTP not configured")
        return

    s = _settings()
    reset_url = f"{s.frontend_url}/reset-password?token={token}"
    html = f"""
    <div style="font-family:sans-serif;max-width:560px;margin:auto;padding:24px">
      <h2 style="color:#1a1a2e">Passwort zurücksetzen</h2>
      <p>Du hast eine Passwort-Rücksetzung für dein FlintPlate-Konto angefordert.</p>
      <p>Klicke auf den folgenden Button, um ein neues Passwort zu setzen. Der Link ist 1 Stunde gültig.</p>
      <a href="{reset_url}"
         style="display:inline-block;margin-top:16px;padding:10px 20px;
                background:#2563eb;color:#fff;border-radius:8px;text-decoration:none">
        Passwort zurücksetzen
      </a>
      <p style="margin-top:16px;color:#666;font-size:12px">
        Wenn du keine Rücksetzung angefordert hast, kannst du diese E-Mail ignorieren.
      </p>
      <p style="color:#888;font-size:12px">
        Link: <a href="{reset_url}" style="color:#2563eb">{reset_url}</a>
      </p>
    </div>
    """
    await send_email(to=email, subject="Passwort zurücksetzen – FlintPlate", html=html)


async def send_verification_email(*, email: str, token: str) -> None:
    """Send an email verification link. No-op if SMTP is not configured."""
    s = _settings()
    verify_url = f"{s.frontend_url}/verify-email?token={token}"
    if not _smtp_configured():
        log.info("Verification email skipped: SMTP not configured")
        return

    html = f"""
    <div style="font-family:sans-serif;max-width:560px;margin:auto;padding:24px">
      <h2 style="color:#1a1a2e">E-Mail-Adresse bestätigen</h2>
      <p>Willkommen bei FlintPlate! Bitte bestätige deine E-Mail-Adresse, um alle Funktionen freizuschalten.</p>
      <a href="{verify_url}"
         style="display:inline-block;margin-top:16px;padding:10px 20px;
                background:#2563eb;color:#fff;border-radius:8px;text-decoration:none">
        E-Mail-Adresse bestätigen
      </a>
      <p style="margin-top:16px;color:#666;font-size:12px">
        Der Link ist 24 Stunden gültig.
      </p>
      <p style="color:#888;font-size:12px">
        Link: <a href="{verify_url}" style="color:#2563eb">{verify_url}</a>
      </p>
    </div>
    """
    await send_email(to=email, subject="E-Mail-Adresse bestätigen – FlintPlate", html=html)


async def send_reminder_email(app: Application) -> None:
    """Send a stale-application reminder email. `app` is an Application ORM object."""
    if not _smtp_configured():
        return

    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.users.models import User

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == app.user_id))
        user = result.scalar_one_or_none()
        if not user:
            return

    subject = f"Neuigkeiten von {app.company}?"
    html = f"""
    <div style="font-family:sans-serif;max-width:560px;margin:auto;padding:24px">
      <h2 style="color:#1a1a2e">Hast du Neuigkeiten von {app.company}?</h2>
      <p>
        Deine Bewerbung als <strong>{app.position}</strong> bei <strong>{app.company}</strong>
        hat seit über {14} Tagen keinen Status-Update erhalten.
      </p>
      <p>Vielleicht ist jetzt ein guter Zeitpunkt für eine freundliche Nachfrage.</p>
      <a href="{_settings().frontend_url}/applications"
         style="display:inline-block;margin-top:16px;padding:10px 20px;
                background:#7F77DD;color:#fff;border-radius:8px;text-decoration:none">
        Bewerbungen öffnen
      </a>
      <p style="margin-top:32px;color:#888;font-size:12px">
        Du erhältst diese E-Mail weil du FlintPlate verwendest.<br>
        Erinnerungen können in den Einstellungen deaktiviert werden.
      </p>
    </div>
    """
    await send_email(to=user.email, subject=subject, html=html)
