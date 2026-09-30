from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from db import get_session
from models import User
from schemas import LoginIn, PhoneIn, RegisterIn, SendCodeOut, TokenOut, UserOut
from services import auth, otp
from services.sms import SmsError

router = APIRouter(prefix="/auth", tags=["auth"])

SessionDep = Annotated[Session, Depends(get_session)]


def _token_out(user: User) -> TokenOut:
    return TokenOut(access_token=auth.create_token(user), user=UserOut.model_validate(user.model_dump()))


@router.post("/register/send-code", response_model=SendCodeOut)
def send_register_code(body: PhoneIn, session: SessionDep) -> SendCodeOut:
    try:
        auth.send_register_code(session, body.phone)
    except auth.AuthError as e:
        raise HTTPException(e.status_code, str(e))
    except otp.OtpCooldown as e:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, str(e), headers={"Retry-After": str(e.retry_in)}
        )
    except SmsError:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Не удалось отправить SMS. Попробуйте позже.")
    return SendCodeOut(sent=True, resend_in=otp.RESEND_COOLDOWN_SECONDS, expires_in=otp.CODE_TTL_SECONDS)


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, session: SessionDep) -> TokenOut:
    try:
        user = auth.register(session, body)
    except auth.AuthError as e:
        raise HTTPException(e.status_code, str(e))
    except otp.OtpError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return _token_out(user)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, session: SessionDep) -> TokenOut:
    try:
        user = auth.authenticate(session, body.phone, body.password)
    except auth.AuthError as e:
        raise HTTPException(e.status_code, str(e))
    return _token_out(user)


@router.get("/me", response_model=UserOut)
def me(user: auth.CurrentUser) -> UserOut:
    return UserOut.model_validate(user.model_dump())
