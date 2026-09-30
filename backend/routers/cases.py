from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, col, select

from db import get_session
from models import Case, CaseStatus, Event, Plan, User
from routers.plans import TodayQuery, plan_out
from schemas import (
    AnswerIn,
    AnswerOut,
    CaseCreate,
    CaseDetailOut,
    CaseListOut,
    CaseOut,
    CaseSummary,
    EventOut,
    InterviewOut,
    PlanOut,
    QuestionOut,
)
from services import interview, overdue, planner
from services.auth import CurrentCurator, CurrentParent

router = APIRouter(prefix="/cases", tags=["cases"])

SessionDep = Annotated[Session, Depends(get_session)]


def _own_case(session: Session, case_id: int, user: User) -> Case:
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Дело не найдено")
    if case.parent_user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет доступа к этому делу")
    return case


def _interview_out(session: Session, case: Case) -> InterviewOut:
    question, answered = interview.current_question(session, case, date.today())
    return InterviewOut(
        case=CaseOut.model_validate(case.model_dump()),
        question=QuestionOut.model_validate(vars(question)) if question else None,
        answered=answered,
        min_questions=interview.MIN_QUESTIONS,
        max_questions=interview.MAX_QUESTIONS,
        done=question is None,
        urgent_reasons=planner.red_flags(case.facts),
    )


@router.post("", response_model=InterviewOut, status_code=status.HTTP_201_CREATED)
def create_case(body: CaseCreate, session: SessionDep, user: CurrentParent) -> InterviewOut:
    case = Case(parent_user_id=user.id, label=body.label.strip())
    session.add(case)
    session.commit()
    session.refresh(case)
    return _interview_out(session, case)


@router.get("/{case_id}/interview", response_model=InterviewOut)
def get_interview(case_id: int, session: SessionDep, user: CurrentParent) -> InterviewOut:
    """Resume the interview: the same question text is shown again (deterministic per case and slot)."""
    return _interview_out(session, _own_case(session, case_id, user))


@router.post("/{case_id}/answers", response_model=InterviewOut)
def answer(case_id: int, body: AnswerIn, session: SessionDep, user: CurrentParent) -> InterviewOut:
    case = _own_case(session, case_id, user)
    try:
        interview.submit_answer(session, case, body, date.today())
    except interview.InterviewOver:
        raise HTTPException(status.HTTP_409_CONFLICT, "Интервью уже завершено")
    except interview.StaleQuestion:
        raise HTTPException(status.HTTP_409_CONFLICT, "Этот вопрос уже не актуален, обновите страницу")
    except interview.AnswerError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))
    return _interview_out(session, case)


@router.post("/{case_id}/plan", response_model=PlanOut)
def create_plan(case_id: int, session: SessionDep, user: CurrentCurator, regenerate: bool = False) -> PlanOut:
    """Curator: build the plan once the interview is over; returns the existing plan unless `regenerate`.

    The parent triggers the first build with POST /parent/cases/{id}/plan, which doesn't return the plan.
    """
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Дело не найдено")
    try:
        plan = planner.generate_plan(session, case, user.id, regenerate=regenerate)
    except planner.PlanNotReady:
        raise HTTPException(status.HTTP_409_CONFLICT, "Интервью ещё не завершено")
    return plan_out(plan, case, date.today())


# ---------------------------------------------------------------------------
# Curator view.


def _full_name(user: User) -> str:
    return " ".join(x for x in (user.last_name, user.first_name, user.middle_name) if x)


@router.get("", response_model=CaseListOut)
def list_cases(session: SessionDep, user: CurrentCurator, today: TodayQuery = None) -> CaseListOut:
    """All cases, most overdue first, with the curator's load against the catalog norm."""
    today = today or date.today()
    rows = session.exec(select(Case, User).join(User, col(Case.parent_user_id) == col(User.id))).all()
    plans = {p.case_id: p for p in session.exec(select(Plan)).all()}

    cases, active = [], 0
    for case, parent in rows:
        plan = plans.get(case.id)
        steps = plan.plan["steps"] if plan else []
        stats = overdue.summary(steps, today)
        if case.status != CaseStatus.interview and stats["steps_done"] < stats["steps_total"]:
            active += 1
        cases.append(
            CaseSummary(
                **CaseOut.model_validate(case.model_dump()).model_dump(),
                **stats,
                parent_name=_full_name(parent),
                plan_id=plan.id if plan else None,
                urgent_reasons=planner.red_flags(case.facts),
            )
        )
    # Red flags first, then the most overdue.
    cases.sort(key=lambda c: (not c.urgent_reasons, -c.worst_level, -c.overdue_count, -c.created_at.timestamp()))
    return CaseListOut(cases=cases, load=overdue.curator_load(active), today=today)


@router.get("/{case_id}", response_model=CaseDetailOut)
def case_detail(case_id: int, session: SessionDep, user: CurrentCurator, today: TodayQuery = None) -> CaseDetailOut:
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Дело не найдено")
    plan = session.exec(select(Plan).where(Plan.case_id == case.id)).first()
    events = session.exec(select(Event).where(Event.case_id == case.id).order_by(col(Event.id))).all()
    return CaseDetailOut(
        case=CaseOut.model_validate(case.model_dump()),
        parent_name=_full_name(session.get(User, case.parent_user_id)),
        facts=case.facts,
        answers=[AnswerOut.model_validate(a.model_dump()) for a in interview.answers_for(session, case)],
        plan=plan_out(plan, case, today or date.today()) if plan else None,
        events=[EventOut.model_validate(e.model_dump()) for e in events],
    )
