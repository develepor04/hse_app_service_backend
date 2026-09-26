"""Email service with dual-backend support: SendGrid and SMTP.

Backend selection via EMAIL_BACKEND env var:
  auto      → SendGrid if SENDGRID_API_KEY is set, otherwise SMTP
  sendgrid  → always use SendGrid
  smtp      → always use SMTP
"""

import logging
import smtplib
import socket
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

# Transient failures worth retrying: DNS blips ("Name or service not known" =
# socket.gaierror), dropped connections and timeouts. A single retry avoids the
# invite email silently dropping when the host briefly can't reach smtp.gmail.com.
_SMTP_RETRIABLE = (
    socket.gaierror,
    smtplib.SMTPServerDisconnected,
    smtplib.SMTPConnectError,
    ConnectionError,
    TimeoutError,
    OSError,
)
_SMTP_MAX_ATTEMPTS = 3
_SMTP_RETRY_DELAY_SEC = 2


def _resolve_backend(s) -> str:
    mode = (s.email_backend or "auto").strip().lower()
    if mode == "sendgrid":
        return "sendgrid"
    if mode == "smtp":
        return "smtp"
    # auto: prefer SendGrid when key is present
    if s.sendgrid_api_key:
        return "sendgrid"
    if s.smtp_host:
        return "smtp"
    return "none"


def _send_via_sendgrid(s, to_email: str, to_name: Optional[str], subject: str, html_content: str) -> bool:
    from_email = s.sendgrid_from_email or "noreply@hse-platform.com"
    from_name  = s.sendgrid_from_name  or "HSE Platform"
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, Email, To, Content

        message = Mail(
            from_email=Email(from_email, from_name),
            to_emails=To(to_email, to_name or to_email),
            subject=subject,
            html_content=Content("text/html", html_content),
        )
        sg = SendGridAPIClient(s.sendgrid_api_key)
        response = sg.send(message)
        logger.info("SendGrid: sent to %s | status=%s", to_email, response.status_code)
        return response.status_code in (200, 202)
    except Exception as exc:
        logger.error("SendGrid send failed to %s: %s", to_email, exc, exc_info=True)
        return False


def _send_via_smtp(s, to_email: str, to_name: Optional[str], subject: str, html_content: str) -> bool:
    if not s.smtp_host:
        logger.error("SMTP_HOST is not configured — email not sent to %s", to_email)
        return False

    # SMTP has its own from address / name; fall back to SendGrid values if not set
    from_email = s.smtp_from_email or s.sendgrid_from_email or "noreply@hse-platform.com"
    from_name  = s.smtp_from_name  or s.sendgrid_from_name  or "HSE Platform"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = f"{to_name} <{to_email}>" if to_name else to_email
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    def _attempt() -> None:
        if s.smtp_use_ssl:
            server = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=15)
        else:
            server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15)
            if s.smtp_use_tls:
                server.ehlo()
                server.starttls()
                server.ehlo()
        try:
            # smtp_user is the correct field name (maps to SMTP_USER env var)
            username = s.smtp_user or s.smtp_username
            if username and s.smtp_password:
                server.login(username, s.smtp_password)
            server.sendmail(from_email, [to_email], msg.as_string())
        finally:
            try:
                server.quit()
            except Exception:
                pass

    for attempt in range(1, _SMTP_MAX_ATTEMPTS + 1):
        try:
            _attempt()
            logger.info(
                "SMTP: sent to %s via %s:%s as <%s> (attempt %s)",
                to_email, s.smtp_host, s.smtp_port, from_email, attempt,
            )
            return True
        except _SMTP_RETRIABLE as exc:
            if attempt < _SMTP_MAX_ATTEMPTS:
                logger.warning(
                    "SMTP transient error to %s (attempt %s/%s): %s — retrying in %ss",
                    to_email, attempt, _SMTP_MAX_ATTEMPTS, exc, _SMTP_RETRY_DELAY_SEC,
                )
                time.sleep(_SMTP_RETRY_DELAY_SEC)
                continue
            logger.error(
                "SMTP send failed to %s after %s attempts: %s",
                to_email, _SMTP_MAX_ATTEMPTS, exc, exc_info=True,
            )
            return False
        except Exception as exc:
            # Non-transient (auth error, malformed message, etc.) — no point retrying.
            logger.error("SMTP send failed to %s: %s", to_email, exc, exc_info=True)
            return False
    return False


def send_email(
    to_email: str,
    subject: str,
    html_content: str,
    to_name: Optional[str] = None,
) -> bool:
    """Send a transactional email via the configured backend (SendGrid or SMTP).

    Returns True on success, False on failure.
    """
    s = get_settings()
    backend = _resolve_backend(s)

    if backend == "sendgrid":
        if not s.sendgrid_api_key:
            logger.error("EMAIL_BACKEND=sendgrid but SENDGRID_API_KEY is not set — email not sent to %s", to_email)
            return False
        return _send_via_sendgrid(s, to_email, to_name, subject, html_content)

    if backend == "smtp":
        return _send_via_smtp(s, to_email, to_name, subject, html_content)

    logger.error(
        "No email backend configured (EMAIL_BACKEND=%r). "
        "Set SENDGRID_API_KEY or SMTP_HOST in .env — email not sent to %s",
        s.email_backend,
        to_email,
    )
    return False


def send_user_invite(
    user_email: str,
    user_name: str,
    organisation_name: str,
    temp_password: str,
    login_url: str,
) -> bool:
    """Send an invite email to a user invited by an org admin."""
    subject = f"You've been invited to {organisation_name} on EHSERA Intelligence"
    html = _build_invite_html(
        admin_name=user_name,
        organisation_name=organisation_name,
        email=user_email,
        temp_password=temp_password,
        login_url=login_url,
    )
    return send_email(to_email=user_email, subject=subject, html_content=html, to_name=user_name)


def send_organisation_invite(
    admin_email: str,
    admin_name: str,
    organisation_name: str,
    temp_password: str,
    login_url: str,
) -> bool:
    """Send an organisation invitation email with login credentials."""
    subject = f"You're invited to join {organisation_name} on EHSERA Intelligence"
    html = _build_invite_html(
        admin_name=admin_name,
        organisation_name=organisation_name,
        email=admin_email,
        temp_password=temp_password,
        login_url=login_url,
    )
    return send_email(to_email=admin_email, subject=subject, html_content=html, to_name=admin_name)


def _build_invite_html(
    admin_name: str,
    organisation_name: str,
    email: str,
    temp_password: str,
    login_url: str,
) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Organisation Invitation</title>
</head>
<body style="margin:0;padding:0;background:#F3F7FF;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F3F7FF;padding:40px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0"
               style="background:#ffffff;border-radius:12px;border:1px solid #D6E4FF;
                      box-shadow:0 4px 20px rgba(0,0,0,0.08);overflow:hidden;">

          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#0B3D91,#1D4ED8);padding:32px 40px;text-align:center;">
              <h1 style="margin:0;color:#ffffff;font-size:24px;font-weight:700;letter-spacing:-0.5px;">
                EHSERA Intelligence
              </h1>
              <p style="margin:8px 0 0;color:rgba(255,255,255,0.8);font-size:14px;">
                Health, Safety &amp; Environment Platform
              </p>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:40px;">
              <h2 style="margin:0 0 16px;color:#0A0A0A;font-size:20px;font-weight:600;">
                Welcome, {admin_name}!
              </h2>
              <p style="margin:0 0 24px;color:#374151;font-size:15px;line-height:1.6;">
                You have been invited to set up and manage
                <strong style="color:#0B3D91;">{organisation_name}</strong>
                on the EHSERA Intelligence platform.
              </p>

              <!-- Credentials box -->
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="background:#F0F4FF;border:1px solid #C7D7FD;border-radius:8px;margin-bottom:28px;">
                <tr>
                  <td style="padding:24px;">
                    <p style="margin:0 0 4px;color:#6B7280;font-size:12px;
                               font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">
                      Your Login Credentials
                    </p>
                    <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:12px;">
                      <tr>
                        <td style="padding:6px 0;color:#374151;font-size:14px;width:130px;">
                          <strong>Login URL</strong>
                        </td>
                        <td style="padding:6px 0;">
                          <a href="{login_url}" style="color:#1D4ED8;font-size:14px;text-decoration:none;">
                            {login_url}
                          </a>
                        </td>
                      </tr>
                      <tr>
                        <td style="padding:6px 0;color:#374151;font-size:14px;"><strong>Email</strong></td>
                        <td style="padding:6px 0;color:#0A0A0A;font-size:14px;">{email}</td>
                      </tr>
                      <tr>
                        <td style="padding:6px 0;color:#374151;font-size:14px;"><strong>Password</strong></td>
                        <td style="padding:6px 0;">
                          <code style="background:#E0E7FF;color:#1D4ED8;padding:3px 8px;
                                       border-radius:4px;font-size:14px;font-weight:600;">
                            {temp_password}
                          </code>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <p style="margin:0 0 24px;color:#6B7280;font-size:13px;line-height:1.5;">
                For security, please change your password after your first login.
                This invitation was sent by the EHSERA Intelligence Super Admin team.
              </p>

              <!-- CTA -->
              <table cellpadding="0" cellspacing="0" style="margin-bottom:32px;">
                <tr>
                  <td style="border-radius:8px;overflow:hidden;">
                    <a href="{login_url}"
                       style="display:inline-block;background:linear-gradient(135deg,#0B3D91,#1D4ED8);
                              color:#ffffff;text-decoration:none;padding:14px 32px;
                              font-size:15px;font-weight:600;border-radius:8px;">
                      Access EHSERA Intelligence
                    </a>
                  </td>
                </tr>
              </table>

              <hr style="border:none;border-top:1px solid #E5E7EB;margin:0 0 24px;" />
              <p style="margin:0;color:#9CA3AF;font-size:12px;line-height:1.5;">
                If you did not expect this invitation, please ignore this email or contact
                <a href="mailto:support@hse-intelligence.com"
                   style="color:#1D4ED8;text-decoration:none;">support@hse-intelligence.com</a>.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background:#F9FAFB;border-top:1px solid #E5E7EB;padding:20px 40px;text-align:center;">
              <p style="margin:0;color:#9CA3AF;font-size:12px;">
                &copy; 2026 EHSERA Intelligence. All rights reserved.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
