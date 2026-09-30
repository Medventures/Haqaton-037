from pydantic import BaseModel, Field, field_validator

from services.phone import normalize_phone

# TODO: case/plan request-response models and LLM output models (see CLAUDE.md).


class PhoneIn(BaseModel):
    phone: str

    @field_validator("phone")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return normalize_phone(v)


class SendCodeOut(BaseModel):
    sent: bool
    resend_in: int
    expires_in: int


class RegisterIn(PhoneIn):
    last_name: str = Field(min_length=1, max_length=100)
    first_name: str = Field(min_length=1, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    code: str = Field(pattern=r"^\d{6}$")

    @field_validator("last_name", "first_name", "middle_name")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class LoginIn(PhoneIn):
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: int
    last_name: str
    first_name: str
    middle_name: str | None
    phone: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
