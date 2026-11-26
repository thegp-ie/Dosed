"""Healthmail (HSE secure clinical email) integration (RFC_2022 s.2.9, 2.10).

- Messages are sent from the signed-in clinician's own Healthmail account.
- Recipients must be on the secure Healthmail network (allow-listed domains), because
  ordinary email is not an acceptable channel for patient data.
- Electronic prescription transfer goes only through Healthmail, only by a licensed
  prescriber, and never for Opiate Substitution Treatment (RFC 2.10.1, 2.10.3, 2.10.9).
- Every send is recorded in outbound_messages and the audit log with the signed-in user.

SMTP/IMAP host names are configuration (EPR_HEALTHMAIL_*), taken from the HSE
Healthmail onboarding pack, not hard-coded here.
"""
from __future__ import annotations

import imaplib
import smtplib
import ssl
from dataclasses import dataclass
from email import message_from_bytes
from email.message import EmailMessage
from email.utils import parseaddr

from ..config import settings


class HealthmailError(Exception):
    pass


@dataclass
class Attachment:
    filename: str
    content: bytes
    mime: str = "application/pdf"


def is_secure_recipient(address: str) -> bool:
    _, addr = parseaddr(address)
    if "@" not in addr:
        return False
    domain = addr.rsplit("@", 1)[1].lower()
    return any(domain == d or domain.endswith("." + d) for d in settings.healthmail_allowed_domains)


def check_recipients(recipients: list[str]) -> None:
    bad = [r for r in recipients if not is_secure_recipient(r)]
    if bad:
        raise HealthmailError(
            "These addresses are not on the secure Healthmail network: " + ", ".join(bad))


def build_message(*, sender: str, to: list[str], subject: str, body: str,
                  attachments: list[Attachment] = ()) -> EmailMessage:
    check_recipients(to)
    if not is_secure_recipient(sender):
        raise HealthmailError("Your account has no Healthmail address set up")
    m = EmailMessage()
    m["From"] = sender
    m["To"] = ", ".join(to)
    m["Subject"] = subject
    m.set_content(body)
    for a in attachments:
        maintype, subtype = a.mime.split("/", 1)
        m.add_attachment(a.content, maintype=maintype, subtype=subtype, filename=a.filename)
    return m


def send(message: EmailMessage, username: str, password: str) -> None:
    if not settings.healthmail_smtp_host:
        raise HealthmailError("Healthmail is not configured (EPR_HEALTHMAIL_SMTP_HOST)")
    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP(settings.healthmail_smtp_host, settings.healthmail_smtp_port, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(username, password)
            s.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        raise HealthmailError(f"Healthmail send failed: {exc}") from exc


def fetch_unseen(username: str, password: str, limit: int = 50) -> list[dict]:
    """Read unseen messages from the Healthmail inbox (headers, text body, attachments)."""
    if not settings.healthmail_imap_host:
        raise HealthmailError("Healthmail is not configured (EPR_HEALTHMAIL_IMAP_HOST)")
    out = []
    with imaplib.IMAP4_SSL(settings.healthmail_imap_host, settings.healthmail_imap_port,
                           ssl_context=ssl.create_default_context()) as im:
        im.login(username, password)
        im.select("INBOX")
        _, data = im.search(None, "UNSEEN")
        for num in data[0].split()[:limit]:
            _, parts = im.fetch(num, "(RFC822)")
            msg = message_from_bytes(parts[0][1])
            body, files = "", []
            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                fn = part.get_filename()
                if fn:
                    files.append({"filename": fn, "content": part.get_payload(decode=True) or b"",
                                  "mime": part.get_content_type()})
                elif part.get_content_type() == "text/plain" and not body:
                    body = (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", "replace")
            out.append({"message_id": msg.get("Message-ID"), "from": msg.get("From"),
                        "subject": msg.get("Subject"), "date": msg.get("Date"), "body": body,
                        "attachments": files})
    return out
