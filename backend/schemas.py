from datetime import date, datetime
from typing import Any
from typing import Literal

from pydantic import BaseModel, Field, NonNegativeInt, field_validator, model_validator

from services.catalog import ServiceId, SlotId
from services.phone import normalize_phone



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


class CaseCreate(BaseModel):
    label: str = Field(default="Мой ребёнок", min_length=1, max_length=100)


class CaseOut(BaseModel):
    id: int
    label: str
    status: str
    created_at: datetime


class QuestionOut(BaseModel):
    slot: SlotId
    group_id: str
    text: str
    hint: str
    kind: Literal["choice", "multi", "age", "months", "text"]
    options: list[str]  # «Не знаю» is not listed: send dont_know=true
    dont_know_label: str = "Не знаю"


class AnswerIn(BaseModel):
    """Exactly one of: dont_know, option (choice), options (multi), value (age/months in months), text."""

    slot: SlotId
    dont_know: bool = False
    option: int | None = Field(default=None, ge=0)
    options: list[NonNegativeInt] | None = Field(default=None, max_length=10)
    value: int | None = Field(default=None, ge=0, le=216)
    text: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _one_answer(self) -> "AnswerIn":
        given = [self.dont_know, self.option is not None, self.options is not None, self.value is not None,
                 bool(self.text and self.text.strip())]
        if sum(given) != 1:
            raise ValueError("give exactly one of dont_know, option, options, value, text")
        return self


class InterviewOut(BaseModel):
    case: CaseOut
    question: QuestionOut | None
    answered: int
    min_questions: int
    max_questions: int
    done: bool


class PlanDocument(BaseModel):
    doc_code: str
    title: str
    on_hand: bool
    from_step: str | None  # the earlier step that produces it
    auto_fetch: str | None  # fetched from a state system, the family doesn't bring it


class PlanStep(BaseModel):
    step_id: str
    service_id: ServiceId
    title: str
    sector: str
    responsible: str
    channel: list[str]
    depends_on: list[str]
    documents: list[PlanDocument]
    legal_source: str
    legal_url: str | None
    due_date: str  # YYYY-MM-DD
    deadline_note: str
    status: Literal["todo", "in_progress", "done", "blocked"]
    priority: int
    rationale: str  # for the curator
    parent_explanation: str
    text_source: Literal["ai", "fallback"]
    warning: str | None
    days_overdue: int = 0  # computed on read against ?today=
    overdue_level: int = 0  # 0 on time, 1 for 1–7 days late, 2 for more


class PlanContent(BaseModel):
    start_date: str
    generated_at: str
    generator: Literal["ai", "fallback"]
    model: str | None
    steps: list[PlanStep]
    undecided: list[ServiceId]  # services unknown facts keep open, for the curator


class OverdueSummary(BaseModel):
    steps_total: int
    steps_done: int
    overdue_count: int
    worst_level: int


class PlanOut(BaseModel):
    id: int
    case_id: int
    case_status: str
    plan: PlanContent
    overdue: OverdueSummary
    today: date
    updated_at: datetime


StepStatus = Literal["todo", "in_progress", "done", "blocked"]


class StepPatch(BaseModel):
    status: StepStatus | None = None
    priority: Literal[1, 2, 3] | None = None
    due_date: date | None = None

    @model_validator(mode="after")
    def _something(self) -> "StepPatch":
        if not self.model_fields_set:
            raise ValueError("nothing to change")
        return self


class StepAdd(BaseModel):
    service_id: ServiceId  # a code outside the catalog is a 422


class StepAddOut(PlanOut):
    added: list[ServiceId]  # the service and the prerequisites it pulled in


class EscalationOut(BaseModel):
    step_id: str
    recipient: str
    days_overdue: int
    overdue_level: int
    warning: str | None
    message: str


class CuratorLoad(BaseModel):
    active_cases: int
    norm_min: int
    norm_max: int
    state: Literal["below", "within", "above"]
    norm_source: str


class CaseSummary(CaseOut, OverdueSummary):
    parent_name: str
    plan_id: int | None


class CaseListOut(BaseModel):
    cases: list[CaseSummary]
    load: CuratorLoad
    today: date


class AnswerOut(BaseModel):
    slot: str
    question_text: str
    raw_answer: str
    parsed: dict[str, Any]
    created_at: datetime


class EventOut(BaseModel):
    id: int
    kind: str
    step_id: str | None
    actor_user_id: int | None
    payload: dict[str, Any]
    created_at: datetime


class CaseDetailOut(BaseModel):
    case: CaseOut
    parent_name: str
    facts: dict[str, Any]  # includes functional scales: curator only, never shown to the parent
    answers: list[AnswerOut]
    plan: PlanOut | None
    events: list[EventOut]


class ParentStep(BaseModel):
    """A plan step as the parent sees it: no curator rationale."""

    step_id: str
    title: str
    responsible: str
    channel: list[str]
    documents: list[PlanDocument]
    legal_source: str
    legal_url: str | None
    due_date: str
    deadline_note: str
    status: StepStatus
    priority: int
    parent_explanation: str
    warning: str | None
    days_overdue: int
    overdue_level: int


class ParentPlanOut(BaseModel):
    case: CaseOut
    steps: list[ParentStep]
    overdue: OverdueSummary
    today: date


class ServiceOut(BaseModel):
    service_id: ServiceId
    title: str
    sector: str
    responsible: str
    mode: Literal["direct", "prerequisite", "trigger"]  # trigger services are added by the curator only
    sla_days: int | None
    sla_unit: str | None
    priority_default: int
    depends_on: list[ServiceId]
    ui_note: str | None
