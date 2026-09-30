"""Curator actions on a plan."""

import copy
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from db import get_session
from models import Case, CaseStatus, Event, Plan
from schemas import EscalationOut, PlanOut, StepAdd, StepAddOut, StepPatch, StepRemove
from services import overdue, planner
from services.safety import contains_diagnosis
from services.auth import CurrentCurator

router = APIRouter(prefix="/plans", tags=["plans"])

SessionDep = Annotated[Session, Depends(get_session)]
TodayQuery = Annotated[date | None, Query(description="Simulated date for overdue (demo); defaults to today")]


def plan_out(plan: Plan, case: Case, today: date) -> PlanOut:
    content = {**plan.plan, "steps": overdue.with_overdue(plan.plan["steps"], today)}
    return PlanOut(
        id=plan.id,
        case_id=case.id,
        case_status=case.status,
        plan=content,
        overdue=overdue.summary(plan.plan["steps"], today),
        today=today,
        updated_at=plan.updated_at,
    )


def _load(session: Session, plan_id: int) -> tuple[Plan, Case]:
    plan = session.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "План не найден")
    return plan, session.get(Case, plan.case_id)


def find_step(content: dict[str, Any], step_id: str) -> dict[str, Any]:
    step = next((s for s in content["steps"] if s["step_id"] == step_id), None)
    if step is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Шаг не найден")
    return step


def mark_completion(step: dict[str, Any], by: str | None) -> None:
    """Record who marked the step done and when (real date, not the simulated one); None clears it."""
    step["completed_by"] = by
    step["completed_at"] = date.today().isoformat() if by else None
    if by is None:
        step.pop("status_before", None)


def save(session: Session, plan: Plan, content: dict[str, Any], event: Event) -> None:
    """Plan JSON and its event row in one transaction."""
    plan.plan = content  # a new dict, so SQLAlchemy sees the change
    plan.updated_at = datetime.now(UTC)
    session.add(plan)
    session.add(event)
    session.commit()
    session.refresh(plan)


@router.patch("/{plan_id}/steps/{step_id}", response_model=PlanOut)
def update_step(
    plan_id: int, step_id: str, body: StepPatch, session: SessionDep, user: CurrentCurator, today: TodayQuery = None
) -> PlanOut:
    plan, case = _load(session, plan_id)
    content = copy.deepcopy(plan.plan)
    step = find_step(content, step_id)
    parent_texts = [t for t in (body.parent_explanation, body.parent_explanation_kk) if t]
    if any(contains_diagnosis(t) for t in parent_texts):
        # The same filter as for AI text: parents never see a diagnosis or a severity.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "В тексте для родителя нельзя называть диагноз, степень или тяжесть состояния",
        )

    changes: dict[str, list[Any]] = {}
    for field in body.model_fields_set:
        new = getattr(body, field)
        if new is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{field} не может быть пустым")
        new = new.isoformat() if isinstance(new, date) else new
        if step.get(field) != new:
            changes[field] = [step.get(field), new]
            step[field] = new
    if "due_date" in changes:
        step["deadline_note"], step["deadline_note_kk"] = planner.CURATOR_DATE_NOTE, planner.CURATOR_DATE_NOTE_KK
    if "status" in changes:
        mark_completion(step, "curator" if step["status"] == "done" else None)
    if {"rationale", "parent_explanation", "parent_explanation_kk"} & changes.keys():
        step["text_source"] = "curator"
    if changes:
        if {"priority", "due_date"} & changes.keys():
            planner.sort_steps(content["steps"])
        save(
            session,
            plan,
            content,
            Event(case_id=case.id, plan_id=plan.id, step_id=step_id, kind="step_updated",
                  actor_user_id=user.id, payload={"changes": changes}),
        )
    return plan_out(plan, case, today or date.today())


@router.post("/{plan_id}/steps", response_model=StepAddOut, status_code=status.HTTP_201_CREATED)
def add_step(plan_id: int, body: StepAdd, session: SessionDep, user: CurrentCurator, today: TodayQuery = None) -> StepAddOut:
    """Add a catalog service (ServiceId only: anything else is a 422) with the prerequisites it still needs."""
    plan, case = _load(session, plan_id)
    today = today or date.today()
    content = copy.deepcopy(plan.plan)
    try:
        added = planner.add_step(content, body.service_id.value, case.facts, today)
    except planner.StepExists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Этот шаг уже есть в плане")
    save(
        session,
        plan,
        content,
        Event(case_id=case.id, plan_id=plan.id, step_id=body.service_id.value, kind="step_added",
              actor_user_id=user.id, payload={"added": added}),
    )
    return StepAddOut(**plan_out(plan, case, today).model_dump(), added=added)


@router.delete("/{plan_id}/steps/{step_id}", response_model=PlanOut)
def remove_step(
    plan_id: int, step_id: str, body: StepRemove, session: SessionDep, user: CurrentCurator, today: TodayQuery = None
) -> PlanOut:
    """Take a step out of the plan, with a reason. Refused while another step depends on it."""
    plan, case = _load(session, plan_id)
    content = copy.deepcopy(plan.plan)
    step = find_step(content, step_id)
    dependents = [s["title"] for s in content["steps"] if step["service_id"] in s["depends_on"]]
    if dependents:
        names = ", ".join(f"«{t}»" for t in dependents)
        raise HTTPException(status.HTTP_409_CONFLICT, f"Сначала удалите зависящие шаги: {names}")

    content["steps"] = [s for s in content["steps"] if s["step_id"] != step_id]
    for other in content["steps"]:  # documents that step would have produced are no longer "from" it
        for doc in other["documents"]:
            if doc["from_step"] == step["service_id"]:
                doc["from_step"] = None
    reason = body.reason.strip()
    content.setdefault("removed", []).append(
        {
            "service_id": step["service_id"],
            "title": step["title"],
            "reason": reason,
            "removed_at": date.today().isoformat(),
            "removed_by": user.id,
        }
    )
    save(
        session,
        plan,
        content,
        Event(case_id=case.id, plan_id=plan.id, step_id=step_id, kind="step_removed", actor_user_id=user.id,
              payload={"title": step["title"], "reason": reason}),
    )
    return plan_out(plan, case, today or date.today())


@router.post("/{plan_id}/approve", response_model=PlanOut)
def approve(plan_id: int, session: SessionDep, user: CurrentCurator, today: TodayQuery = None) -> PlanOut:
    """Approval gate: the parent sees the plan only after this."""
    plan, case = _load(session, plan_id)
    if case.status != CaseStatus.approved:
        case.status = CaseStatus.approved
        session.add(case)
        session.add(Event(case_id=case.id, plan_id=plan.id, kind="plan_approved", actor_user_id=user.id))
        session.commit()
        session.refresh(case)
    return plan_out(plan, case, today or date.today())


@router.post("/{plan_id}/steps/{step_id}/escalate", response_model=EscalationOut)
def escalate(
    plan_id: int, step_id: str, session: SessionDep, user: CurrentCurator, today: TodayQuery = None
) -> EscalationOut:
    """Log the escalation and return a pre-filled message to the responsible organization."""
    plan, case = _load(session, plan_id)
    today = today or date.today()
    step = find_step(plan.plan, step_id)
    if overdue.overdue_days(step, today) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Шаг не просрочен")
    result = overdue.escalation_message(step, case.label, today)
    session.add(
        Event(case_id=case.id, plan_id=plan.id, step_id=step_id, kind="escalated", actor_user_id=user.id,
              payload={"today": today.isoformat(), "days_overdue": result["days_overdue"],
                       "recipient": result["recipient"]})
    )
    session.commit()
    return EscalationOut(step_id=step_id, **result)
