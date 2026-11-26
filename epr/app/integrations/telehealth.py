"""Remote (video) consultations on a self-hosted Jitsi Meet server.

Why self-hosted Jitsi: video and audio stay on infrastructure the practice controls in
the EU, no third-party processor sees the call, and nothing is recorded by default.
Jitsi is configured with JWT ("token") authentication so only links issued by the EPR
can open a room; the clinician joins as moderator and the patient waits in the lobby.

Medico-legal points built into the workflow (Medical Council guidance on telemedicine;
Medical Protection Ireland advice on remote consulting):
- Remote consultations are intended for patients already known to the practice.
- The note records that the consultation was remote, that the patient consented, and
  that their identity was confirmed.
- No recording unless separately agreed and stored as part of the record.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import quote, urlparse

from ..config import settings


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def new_room_name() -> str:
    # Unguessable and carries no patient information.
    return "c-" + secrets.token_hex(12)


def jitsi_token(room: str, display_name: str, moderator: bool, ttl_seconds: int = 3 * 3600) -> str:
    if not settings.jitsi_app_secret:
        raise RuntimeError("EPR_JITSI_APP_SECRET is not set")
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "aud": "jitsi", "iss": settings.jitsi_app_id, "sub": urlparse(settings.jitsi_base_url).hostname,
        "room": room, "iat": now, "nbf": now - 30, "exp": now + ttl_seconds,
        "context": {"user": {"name": display_name, "moderator": moderator},
                    "features": {"recording": False, "livestreaming": False}},
        "moderator": moderator,
    }
    signing_input = _b64(json.dumps(header, separators=(",", ":")).encode()) + "." + \
        _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(settings.jitsi_app_secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return signing_input + "." + _b64(sig)


def room_url(room: str, token: str) -> str:
    base = settings.jitsi_base_url.rstrip("/")
    return f"{base}/{quote(room)}?jwt={token}#config.prejoinConfig.enabled=true"


def new_patient_link() -> tuple[str, str]:
    """Returns (token for the patient URL, sha256 to store). The token is never stored."""
    token = secrets.token_urlsafe(24)
    return token, hashlib.sha256(token.encode()).hexdigest()


def hash_link_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def patient_join_url(token: str) -> str:
    return settings.public_base_url.rstrip("/") + "/v/" + token
