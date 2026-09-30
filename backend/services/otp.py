"""One-time SMS codes, stored in the `otp_codes` table.

Not kept in memory: on Vercel each request can land on a different instance, so "send code" and
"register" must share state through the database. Only a hash of the code is stored.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from models import OtpCode

CODE_TTL_SECONDS = 300
RESEND_COOLDOWN_SECONDS = 60
MAX_ATTEMPTS = 5


class OtpError(Exception):
    pass


class OtpCooldown(OtpError):
    def __init__(self, retry_in: int) -> None:
        super().__init__(f"Повторная отправка через {retry_in} с")
        self.retry_in = retry_in


def _hash(phone: str, code: str) -> str:
    return hashlib.sha256(f"{phone}:{code}".encode()).hexdigest()


def _aware(dt: datetime) -> datetime:
    # SQLite returns naive datetimes even for timezone-aware columns.
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def issue_code(session: Session, phone: str) -> str:
    now = datetime.now(UTC)
    entry = session.get(OtpCode, phone)
    if entry:
        elapsed = (now - _aware(entry.sent_at)).total_seconds()
        if elapsed < RESEND_COOLDOWN_SECONDS:
            raise OtpCooldown(int(RESEND_COOLDOWN_SECONDS - elapsed) + 1)
    else:
        entry = OtpCode(phone=phone)
    code = f"{secrets.randbelow(10**6):06d}"
    entry.code_hash = _hash(phone, code)
    entry.sent_at = now
    entry.expires_at = now + timedelta(seconds=CODE_TTL_SECONDS)
    entry.attempts = 0
    session.add(entry)
    try:
        session.commit()
    except IntegrityError:  # a parallel request for the same phone won the insert
        session.rollback()
        raise OtpCooldown(RESEND_COOLDOWN_SECONDS)
    return code


def discard_code(session: Session, phone: str) -> None:
    if entry := session.get(OtpCode, phone):
        session.delete(entry)
        session.commit()


def verify_code(session: Session, phone: str, code: str) -> None:
    """Raise OtpError unless the code matches. A matched code is deleted in the caller's commit."""
    # Row lock (Postgres) so parallel guesses can't get past MAX_ATTEMPTS.
    entry = session.get(OtpCode, phone, with_for_update=True)
    if entry is None or datetime.now(UTC) > _aware(entry.expires_at):
        if entry:
            session.delete(entry)
            session.commit()
        raise OtpError("Код истёк или не запрашивался. Запросите новый код.")
    if entry.attempts >= MAX_ATTEMPTS:
        session.delete(entry)
        session.commit()
        raise OtpError("Слишком много попыток. Запросите новый код.")
    if not hmac.compare_digest(entry.code_hash, _hash(phone, code)):
        entry.attempts += 1
        session.add(entry)
        session.commit()
        raise OtpError("Неверный код")
    session.delete(entry)
