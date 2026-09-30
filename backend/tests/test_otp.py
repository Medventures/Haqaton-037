from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import models
from services import otp

PHONE = "77010000009"


@pytest.fixture
def engine():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(e)
    return e


def test_code_survives_across_sessions(engine):
    # Two sessions stand in for two serverless instances: send-code on one, register on another.
    with Session(engine) as s:
        code = otp.issue_code(s, PHONE)
    with Session(engine) as s:
        otp.verify_code(s, PHONE, code)
        s.commit()
    with Session(engine) as s:
        assert s.get(models.OtpCode, PHONE) is None  # consumed


def test_only_a_hash_is_stored(engine):
    with Session(engine) as s:
        code = otp.issue_code(s, PHONE)
        assert code not in s.get(models.OtpCode, PHONE).code_hash


def test_resend_cooldown(engine):
    with Session(engine) as s:
        otp.issue_code(s, PHONE)
        with pytest.raises(otp.OtpCooldown):
            otp.issue_code(s, PHONE)
        entry = s.get(models.OtpCode, PHONE)
        entry.sent_at = datetime.now(UTC) - timedelta(seconds=otp.RESEND_COOLDOWN_SECONDS + 1)
        s.commit()
        otp.issue_code(s, PHONE)


def test_wrong_code_attempts_are_limited(engine):
    with Session(engine) as s:
        code = otp.issue_code(s, PHONE)
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(otp.MAX_ATTEMPTS):
            with pytest.raises(otp.OtpError, match="Неверный код"):
                otp.verify_code(s, PHONE, wrong)
        with pytest.raises(otp.OtpError, match="Слишком много"):
            otp.verify_code(s, PHONE, code)  # even the right code is refused now


def test_expired_code(engine):
    with Session(engine) as s:
        code = otp.issue_code(s, PHONE)
        s.get(models.OtpCode, PHONE).expires_at = datetime.now(UTC) - timedelta(seconds=1)
        s.commit()
        with pytest.raises(otp.OtpError, match="истёк"):
            otp.verify_code(s, PHONE, code)


def test_discard_allows_immediate_resend(engine):
    with Session(engine) as s:
        otp.issue_code(s, PHONE)
        otp.discard_code(s, PHONE)
        otp.issue_code(s, PHONE)
