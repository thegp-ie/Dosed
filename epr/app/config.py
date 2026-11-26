"""Runtime configuration, read from environment variables (see .env.example).

Nothing here has a production-safe default for secrets: the app refuses to start
in production mode if the encryption key or secret key are missing.
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    env: str = field(default_factory=lambda: os.environ.get("EPR_ENV", "development"))
    database_url: str = field(
        default_factory=lambda: os.environ.get("EPR_DATABASE_URL", "sqlite:///./epr-dev.db")
    )
    # 32-byte key, base64. Encrypts clinical free text and identifiers at field level.
    data_key_b64: str = field(default_factory=lambda: os.environ.get("EPR_DATA_KEY", ""))
    # Separate key for blind indexes (searchable hashes of PPSN etc.).
    index_key_b64: str = field(default_factory=lambda: os.environ.get("EPR_INDEX_KEY", ""))
    secret_key: str = field(default_factory=lambda: os.environ.get("EPR_SECRET_KEY", ""))

    practice_name: str = field(default_factory=lambda: os.environ.get("EPR_PRACTICE_NAME", "Demo Practice"))
    practice_address: str = field(default_factory=lambda: os.environ.get("EPR_PRACTICE_ADDRESS", ""))
    practice_healthlink_id: str = field(default_factory=lambda: os.environ.get("EPR_HEALTHLINK_PRACTICE_ID", ""))

    session_idle_minutes: int = field(default_factory=lambda: int(os.environ.get("EPR_SESSION_IDLE_MINUTES", "15")))
    session_max_hours: int = field(default_factory=lambda: int(os.environ.get("EPR_SESSION_MAX_HOURS", "10")))
    require_mfa: bool = field(default_factory=lambda: _bool("EPR_REQUIRE_MFA", True))
    cookie_secure: bool = field(default_factory=lambda: _bool("EPR_COOKIE_SECURE", True))

    # Healthmail (HSE secure email). Host names are configured, not hard-coded:
    # take the current values from the HSE Healthmail onboarding pack.
    healthmail_smtp_host: str = field(default_factory=lambda: os.environ.get("EPR_HEALTHMAIL_SMTP_HOST", ""))
    healthmail_smtp_port: int = field(default_factory=lambda: int(os.environ.get("EPR_HEALTHMAIL_SMTP_PORT", "587")))
    healthmail_imap_host: str = field(default_factory=lambda: os.environ.get("EPR_HEALTHMAIL_IMAP_HOST", ""))
    healthmail_imap_port: int = field(default_factory=lambda: int(os.environ.get("EPR_HEALTHMAIL_IMAP_PORT", "993")))
    healthmail_user: str = field(default_factory=lambda: os.environ.get("EPR_HEALTHMAIL_USER", ""))
    healthmail_password: str = field(default_factory=lambda: os.environ.get("EPR_HEALTHMAIL_PASSWORD", ""))
    # Recipient domains that count as the secure Healthmail network.
    healthmail_allowed_domains: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            d.strip().lower()
            for d in os.environ.get("EPR_HEALTHMAIL_ALLOWED_DOMAINS", "healthmail.ie,hse.ie").split(",")
            if d.strip()
        )
    )

    # Healthlink. "directory" mode reads/writes HL7 files in folders (works with the
    # Healthlink client or any file-drop bridge). "disabled" turns it off.
    healthlink_mode: str = field(default_factory=lambda: os.environ.get("EPR_HEALTHLINK_MODE", "directory"))
    healthlink_inbound_dir: str = field(default_factory=lambda: os.environ.get("EPR_HEALTHLINK_INBOUND_DIR", "./healthlink/in"))
    healthlink_outbound_dir: str = field(default_factory=lambda: os.environ.get("EPR_HEALTHLINK_OUTBOUND_DIR", "./healthlink/out"))
    healthlink_archive_dir: str = field(default_factory=lambda: os.environ.get("EPR_HEALTHLINK_ARCHIVE_DIR", "./healthlink/archive"))

    # Remote consultations: self-hosted Jitsi Meet with JWT (token) authentication.
    jitsi_base_url: str = field(default_factory=lambda: os.environ.get("EPR_JITSI_BASE_URL", "https://meet.example.ie"))
    jitsi_app_id: str = field(default_factory=lambda: os.environ.get("EPR_JITSI_APP_ID", "epr"))
    jitsi_app_secret: str = field(default_factory=lambda: os.environ.get("EPR_JITSI_APP_SECRET", ""))
    public_base_url: str = field(default_factory=lambda: os.environ.get("EPR_PUBLIC_BASE_URL", "https://epr.example.ie"))

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    def data_key(self) -> bytes:
        return _key(self.data_key_b64, "EPR_DATA_KEY", self.is_production, b"dev-data-key")

    def index_key(self) -> bytes:
        return _key(self.index_key_b64, "EPR_INDEX_KEY", self.is_production, b"dev-index-key")

    def validate(self) -> None:
        if self.is_production:
            missing = [n for n, v in (
                ("EPR_DATA_KEY", self.data_key_b64),
                ("EPR_INDEX_KEY", self.index_key_b64),
                ("EPR_SECRET_KEY", self.secret_key),
            ) if not v]
            if missing:
                raise RuntimeError(f"Missing required settings in production: {', '.join(missing)}")
            if self.database_url.startswith("sqlite"):
                raise RuntimeError("Use PostgreSQL in production (EPR_DATABASE_URL).")
            self.data_key()
            self.index_key()


def _key(b64: str, name: str, production: bool, dev_seed: bytes) -> bytes:
    if not b64:
        if production:
            raise RuntimeError(f"{name} is required in production")
        # Deterministic development key. Never used when EPR_ENV=production.
        import hashlib
        return hashlib.sha256(dev_seed).digest()
    raw = base64.b64decode(b64)
    if len(raw) != 32:
        raise RuntimeError(f"{name} must be 32 bytes, base64-encoded")
    return raw


settings = Settings()
