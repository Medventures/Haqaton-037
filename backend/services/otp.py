"""One-time SMS codes. Kept in memory on purpose: the DB stores only user profile + password hash."""

import hmac
import secrets
import threading
import time
from dataclasses import dataclass

CODE_TTL_SECONDS = 300
RESEND_COOLDOWN_SECONDS = 60
MAX_ATTEMPTS = 5


class OtpError(Exception):
    pass


class OtpCooldown(OtpError):
    def __init__(self, retry_in: int) -> None:
        super().__init__(f"Повторная отправка через {retry_in} с")
        self.retry_in = retry_in


@dataclass
class _Entry:
    code: str
    expires_at: float
    sent_at: float
    attempts: int = 0


_store: dict[str, _Entry] = {}
_lock = threading.Lock()


def issue_code(phone: str) -> str:
    now = time.monotonic()
    with _lock:
        entry = _store.get(phone)
        if entry and now - entry.sent_at < RESEND_COOLDOWN_SECONDS:
            raise OtpCooldown(int(RESEND_COOLDOWN_SECONDS - (now - entry.sent_at)) + 1)
        code = f"{secrets.randbelow(10**6):06d}"
        _store[phone] = _Entry(code=code, expires_at=now + CODE_TTL_SECONDS, sent_at=now)
        return code


def discard_code(phone: str) -> None:
    with _lock:
        _store.pop(phone, None)


def verify_code(phone: str, code: str) -> None:
    """Raise OtpError unless the code matches. A matched code is consumed."""
    now = time.monotonic()
    with _lock:
        entry = _store.get(phone)
        if entry is None or now > entry.expires_at:
            _store.pop(phone, None)
            raise OtpError("Код истёк или не запрашивался. Запросите новый код.")
        if entry.attempts >= MAX_ATTEMPTS:
            _store.pop(phone, None)
            raise OtpError("Слишком много попыток. Запросите новый код.")
        if not hmac.compare_digest(entry.code, code):
            entry.attempts += 1
            raise OtpError("Неверный код")
        del _store[phone]
