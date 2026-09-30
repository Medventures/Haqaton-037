from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

JSONType = JSON().with_variant(JSONB(), "postgresql")


def _now() -> datetime:
    return datetime.now(UTC)


def _created_at() -> Any:
    return Field(default_factory=_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    last_name: str = Field(max_length=100)
    first_name: str = Field(max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    phone: str = Field(max_length=20, unique=True, index=True)
    password_hash: str = Field(max_length=255)


class CaseStatus(StrEnum):
    interview = "interview"
    draft = "draft"
    approved = "approved"


class Case(SQLModel, table=True):
    __tablename__ = "cases"

    id: int | None = Field(default=None, primary_key=True)
    parent_user_id: int = Field(foreign_key="users.id", index=True)
    label: str = Field(max_length=100)
    status: str = Field(default=CaseStatus.interview, max_length=20)
    # Fact key → value (facts.json vocabulary). Reassign the dict on change: JSON columns don't track mutation.
    facts: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONType, nullable=False))
    created_at: datetime = _created_at()


class InterviewAnswer(SQLModel, table=True):
    __tablename__ = "interview_answers"

    id: int | None = Field(default=None, primary_key=True)
    case_id: int = Field(foreign_key="cases.id", index=True)
    slot: str = Field(max_length=50)
    group_id: str = Field(max_length=50)
    question_text: str = Field(max_length=500)
    raw_answer: str = Field(max_length=1000)
    # Facts this answer set, {fact: value}; a «Не знаю» answer stores {slot: null}.
    parsed: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONType, nullable=False))
    created_at: datetime = _created_at()


class Plan(SQLModel, table=True):
    __tablename__ = "plans"

    id: int | None = Field(default=None, primary_key=True)
    case_id: int = Field(foreign_key="cases.id", unique=True, index=True)
    plan: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONType, nullable=False))
    created_at: datetime = _created_at()
    updated_at: datetime = _created_at()


class Event(SQLModel, table=True):
    __tablename__ = "events"

    id: int | None = Field(default=None, primary_key=True)
    case_id: int = Field(foreign_key="cases.id", index=True)
    plan_id: int | None = Field(default=None, foreign_key="plans.id")
    step_id: str | None = Field(default=None, max_length=50)
    kind: str = Field(max_length=30)  # e.g. step_updated, step_added, approved, escalated
    actor_user_id: int | None = Field(default=None, foreign_key="users.id")
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONType, nullable=False))
    created_at: datetime = _created_at()
