import hashlib
import hmac
import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session, select

from db import get_session
from models import User
from schemas import RegisterIn
from services import otp
from services.sms import send_sms

log = logging.getLogger("aqylroute.auth")

JWT_ALGORITHM = "HS256"
JWT_TTL_HOURS = int(os.getenv("JWT_TTL_HOURS", "72"))
_JWT_SECRET = os.getenv("JWT_SECRET")
if not _JWT_SECRET:
    log.warning("JWT_SECRET not set, using a random one: tokens reset on restart")
    _JWT_SECRET = secrets.token_urlsafe(32)
elif _JWT_SECRET == "change-me":
    log.warning("JWT_SECRET is the .env.example placeholder: anyone can forge tokens. Set a random value.")

# scrypt parameters (stdlib, no native deps)
_N, _R, _P = 2**14, 8, 1


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> None:
        super().__init__(message)
        self.status_code = status_code


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        candidate = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p)
        )
    except ValueError:
        return False
    return hmac.compare_digest(candidate.hex(), digest)


def create_token(user: User) -> str:
    payload = {"sub": str(user.id), "exp": datetime.now(UTC) + timedelta(hours=JWT_TTL_HOURS)}
    return jwt.encode(payload, _JWT_SECRET, algorithm=JWT_ALGORITHM)


def _get_user_by_phone(session: Session, phone: str) -> User | None:
    return session.exec(select(User).where(User.phone == phone)).first()


def send_register_code(session: Session, phone: str) -> None:
    if _get_user_by_phone(session, phone):
        raise AuthError("Этот номер уже зарегистрирован", status.HTTP_409_CONFLICT)
    code = otp.issue_code(phone)
    try:
        send_sms(phone, f"AqylRoute: код подтверждения {code}")
    except Exception:
        otp.discard_code(phone)  # let the user retry immediately
        raise


def register(session: Session, data: RegisterIn) -> User:
    if _get_user_by_phone(session, data.phone):
        raise AuthError("Этот номер уже зарегистрирован", status.HTTP_409_CONFLICT)
    otp.verify_code(data.phone, data.code)
    user = User(
        last_name=data.last_name,
        first_name=data.first_name,
        middle_name=data.middle_name,
        phone=data.phone,
        password_hash=hash_password(data.password),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def authenticate(session: Session, phone: str, password: str) -> User:
    user = _get_user_by_phone(session, phone)
    if not user or not verify_password(password, user.password_hash):
        raise AuthError("Неверный номер или пароль", status.HTTP_401_UNAUTHORIZED)
    return user


_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[Session, Depends(get_session)],
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Требуется вход", headers={"WWW-Authenticate": "Bearer"}
    )
    if creds is None:
        raise unauthorized
    try:
        payload = jwt.decode(creds.credentials, _JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user = session.get(User, int(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized
    if user is None:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
