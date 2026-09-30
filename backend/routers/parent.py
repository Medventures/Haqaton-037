"""Parent-facing endpoints. A parent sees only their own cases, and the plan only after curator approval."""

import copy
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, col, select

from db import get_session
from models import Case, CaseStatus, Event, Plan
from routers.plans import TodayQuery, find_step, mark_completion, save
from schemas import CaseOut, ParentPlanOut, ParentStep, StepDoneIn
from services import overdue, planner
from services.auth import CurrentParent

router = APIRouter(prefix="/parent", tags=["parent"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/cases", response_model=list[CaseOut])
def my_cases(session: SessionDep, user: CurrentParent) -> list[CaseOut]:
    stmt = select(Case).where(Case.parent_user_id == user.id).order_by(col(Case.created_at).desc())
    return [CaseOut.model_validate(c.model_dump()) for c in session.exec(stmt).all()]


def _own_case(session: Session, case_id: int, user_id: int) -> Case:
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Дело не найдено")
    if case.parent_user_id != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нет доступа к этому делу")
    return case


@router.post("/cases/{case_id}/plan", response_model=CaseOut)
def submit_interview(case_id: int, session: SessionDep, user: CurrentParent) -> CaseOut:
    """After the last answer: build the plan and send it to the curator. The plan itself is not returned."""
    case = _own_case(session, case_id, user.id)
    try:
        planner.generate_plan(session, case, user.id, regenerate=False)
    except planner.PlanNotReady:
        raise HTTPException(status.HTTP_409_CONFLICT, "Интервью ещё не завершено")
    session.refresh(case)  # expired by the commit
    return CaseOut.model_validate(case.model_dump())


def _approved_plan(session: Session, case: Case) -> Plan:
    plan = session.exec(select(Plan).where(Plan.case_id == case.id)).first()
    if case.status != CaseStatus.approved or plan is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "План на проверке у куратора")
    return plan


def _plan_out(case: Case, plan: Plan, today: date | None) -> ParentPlanOut:
    today = today or date.today()
    steps = overdue.with_overdue(plan.plan["steps"], today)
    return ParentPlanOut(
        case=CaseOut.model_validate(case.model_dump()),
        steps=[ParentStep.model_validate(s) for s in steps],  # drops the curator's rationale
        overdue=overdue.summary(plan.plan["steps"], today),
        today=today,
    )


@router.get("/cases/{case_id}", response_model=ParentPlanOut)
def my_plan(case_id: int, session: SessionDep, user: CurrentParent, today: TodayQuery = None) -> ParentPlanOut:
    """403 unless it is the parent's own case and the curator has approved the plan."""
    case = _own_case(session, case_id, user.id)
    return _plan_out(case, _approved_plan(session, case), today)


@router.patch("/cases/{case_id}/steps/{step_id}", response_model=ParentPlanOut)
def mark_step(
    case_id: int, step_id: str, body: StepDoneIn, session: SessionDep, user: CurrentParent, today: TodayQuery = None
) -> ParentPlanOut:
    """The parent marks a step of their approved plan as done, or undoes their own mark.

    Only the status changes; the curator sees «отмечено родителем» and the case history records it.
    """
    case = _own_case(session, case_id, user.id)
    plan = _approved_plan(session, case)
    content = copy.deepcopy(plan.plan)
    step = find_step(content, step_id)
    old_status = step["status"]

    if body.done:
        if old_status == "done":
            return _plan_out(case, plan, today)
        step["status_before"] = old_status  # restored on undo
        step["status"] = "done"
        mark_completion(step, "parent")
        kind = "step_done_by_parent"
    else:
        if old_status != "done":
            return _plan_out(case, plan, today)
        if step.get("completed_by") != "parent":
            raise HTTPException(status.HTTP_409_CONFLICT, "Шаг отметил куратор — отменить может только он")
        step["status"] = step.get("status_before") or "todo"
        mark_completion(step, None)
        kind = "step_reopened_by_parent"

    save(
        session,
        plan,
        content,
        Event(case_id=case.id, plan_id=plan.id, step_id=step_id, kind=kind, actor_user_id=user.id,
              payload={"changes": {"status": [old_status, step["status"]]}}),
    )
    session.refresh(case)
    return _plan_out(case, plan, today)
