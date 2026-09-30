"""Plan builder. Code decides the steps, dates, documents and legal sources from the catalog;
the AI only writes `rationale` (for the curator), `parent_explanation` and a priority per step.
Without OPENAI_API_KEY, or when the AI output fails the checks, the texts come from the catalog.
"""

import json
import logging
import os
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel
from sqlmodel import Session, select

from models import Case, CaseStatus, Event, Plan
from schemas import MAX_EXPLANATION, MAX_RATIONALE
from services import llm
from services.catalog import (
    DOCUMENTS,
    LEGAL_SOURCES,
    RULES,
    SERVICES,
    ServiceId,
    kk_document,
    kk_service,
    legal_source_text,
)
from services.eligibility import build_profile, dependency_order, select_services, with_prerequisites
from services.interview import current_question
from services.safety import DiagnosisInOutput, assert_no_diagnosis

log = logging.getLogger("aqylroute.planner")

ASSIGNED_DAYS = 14  # services without a statutory deadline
ASSIGNED_NOTE = "нормативного срока нет — срок назначен куратором"
ASSIGNED_NOTE_KK = "нормативтік мерзім жоқ — мерзімді куратор белгіледі"
CURATOR_DATE_NOTE = "Срок изменён куратором"
CURATOR_DATE_NOTE_KK = "Мерзімді куратор өзгертті"

# Facts the AI may see. Functional scales and months_since_diagnosis describe the child's health
# and are never passed to the AI (PLAN.md, risks).
_AI_VISIBLE_FACTS = (
    "age_months", "region", "goal", "setting", "documents_on_hand", "has_doctor_conclusion",
    "seeking_disability", "current_support", "benefits_received", "wants_ssu", "urgent", "has_curator",
)


# ---------------------------------------------------------------------------
# Steps and deadlines (code only)


def build_steps(facts: dict[str, Any], start: date) -> tuple[list[dict[str, Any]], list[str]]:
    """Plan steps in dependency order, plus the services unknown facts keep undecided."""
    selection = select_services(build_profile(facts, start))
    return [_step(code, facts, start, selection.selected) for code in selection.selected], selection.undecided


def _step(code: str, facts: dict[str, Any], start: date, plan_codes: list[str]) -> dict[str, Any]:
    service = SERVICES[code]
    return {
        "step_id": code,
        "service_id": code,
        "title": service["title_ru"],
        "title_kk": kk_service(code, "title"),
        "sector": service["domain"],
        "responsible": service["provider_org"],
        "responsible_kk": kk_service(code, "provider_org"),
        "channel": service.get("channel", []),
        "depends_on": [d for d in service["depends_on"] if d in plan_codes],
        "documents": [],  # filled by _fill_documents once all steps exist
        "legal_source": legal_source_text(code),
        "legal_url": LEGAL_SOURCES[service["legal_source"]].get("url"),
        "due_date": None,  # filled by _fill_due_dates
        "deadline_note": "",
        "deadline_note_kk": None,
        "status": "todo",
        "completed_by": None,
        "completed_at": None,
        "priority": service["priority_default"],
        "rationale": "",
        "parent_explanation": "",
        "parent_explanation_kk": None,
        "text_source": "fallback",
        "warning": service.get("financial_risk"),
    }


def add_working_days(start: date, days: int) -> date:
    """Skip Saturdays and Sundays. Public holidays are not in the catalog, so they are not skipped."""
    d = start
    while days > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            days -= 1
    return d


def next_month_day(start: date, month_day: str) -> date:
    """The next MM-DD on or after `start`."""
    month, day = (int(x) for x in month_day.split("-"))
    candidate = date(start.year, month, day)
    return candidate if candidate >= start else date(start.year + 1, month, day)


def _fill_due_dates(
    steps: list[dict[str, Any]], facts: dict[str, Any], case_start: date, prior: list[dict[str, Any]] = ()
) -> None:
    """Steps come in dependency order, so each step's prerequisites already have dates.

    `prior` are steps already in the plan; new steps can depend on them.
    """
    due: dict[str, date] = {s["service_id"]: date.fromisoformat(s["due_date"]) for s in prior}
    for step in steps:
        service = SERVICES[step["service_id"]]
        start = max([case_start, *(due[d] for d in step["depends_on"])])
        sla, unit = service.get("sla_days"), service.get("sla_unit")

        if service.get("deadline_type") == "calendar_date":
            day = next_month_day(start, service["deadline_rule"]["enroll_by"])
            note = f"Крайняя дата — {day.strftime('%d.%m')} (нормативная дата, не гарантия)"
            note_kk = f"Соңғы күн — {day.strftime('%d.%m')} (нормативтік күн, кепілдік емес)"
        elif sla is None:
            day, note, note_kk = start + timedelta(days=ASSIGNED_DAYS), ASSIGNED_NOTE, ASSIGNED_NOTE_KK
        else:
            working = unit == "working"
            note = (f"Нормативный срок — {sla} {'рабочих' if working else 'календарных'} дн. "
                    "Это предел по закону, а не гарантия")
            note_kk = (f"Нормативтік мерзім — {sla} {'жұмыс' if working else 'күнтізбелік'} күн. "
                       "Бұл заңдағы шек, кепілдік емес")
            if step["service_id"] == "MED_DIAGNOSIS_WAIT" and facts.get("months_since_diagnosis") is not None:
                sla = max(0, sla - 30 * facts["months_since_diagnosis"])  # observation already under way
                note = f"Направить на МСЭ можно не раньше чем через 4 месяца наблюдения, осталось около {sla} дн."
                note_kk = f"МӘС-ке жолдауды 4 ай бақылаудан кейін ғана алуға болады, шамамен {sla} күн қалды"
            day = add_working_days(start, sla) if working else start + timedelta(days=sla)
        due[step["service_id"]] = day
        step["due_date"] = day.isoformat()
        step["deadline_note"], step["deadline_note_kk"] = note, note_kk


def _fill_documents(steps: list[dict[str, Any]], facts: dict[str, Any], prior: list[dict[str, Any]] = ()) -> None:
    on_hand = set(facts.get("documents_on_hand") or [])
    produced_by: dict[str, str] = {}
    for step in prior:
        for doc in SERVICES[step["service_id"]].get("produces") or []:
            produced_by.setdefault(doc, step["service_id"])
    for step in steps:  # dependency order: earlier steps' results count for later ones
        service = SERVICES[step["service_id"]]
        docs = []
        for doc in service["documents_required"]:
            producer = produced_by.get(doc)
            # A prerequisite step in the plan renews the document (e.g. a new ПМПК conclusion for school).
            renewed = producer in step["depends_on"]
            docs.append(
                {
                    "doc_code": doc,
                    "title": DOCUMENTS[doc]["title"],
                    "title_kk": kk_document(doc),
                    "on_hand": doc in on_hand and not renewed,
                    "from_step": producer if renewed or doc not in on_hand else None,
                    "auto_fetch": DOCUMENTS[doc].get("auto_fetch"),
                }
            )
        step["documents"] = docs
        for doc in service.get("produces") or []:
            produced_by.setdefault(doc, step["service_id"])


def fallback_texts(code: str) -> tuple[str, str]:
    """(rationale, parent_explanation) straight from the checked catalog.

    `why_short` is not used for parents: it is missing for many services and written for the team.
    """
    service = SERVICES[code]
    rationale = RULES[code].get("note") or service.get("why_short") or service["title_ru"]
    explanation = f"{service['title_ru']}. Куда обращаться: {service['provider_org']}."
    if service.get("result"):
        first_sentence = first_sentence_of(service["result"])
        explanation += f" Что вы получите: {first_sentence[0].lower()}{first_sentence[1:]}."
    return rationale, explanation


def first_sentence_of(text: str) -> str:
    """Up to the first full stop that starts a new sentence (not «прил. 4»), without the stop."""
    return re.split(r"(?<=[.!?])\s+(?=[А-ЯЁA-ZӘІҢҒҮҰҚӨҺ])", text.strip())[0].rstrip(".")


def red_flags(facts: dict[str, Any]) -> list[str]:
    """Answers that need a doctor soon, whatever the plan says (shown to the parent at once)."""
    return list(facts.get("red_flags") or [])


def fallback_explanation_kk(code: str) -> str | None:
    """The Kazakh parent text from the catalog translation, or None without one."""
    title, org = kk_service(code, "title"), kk_service(code, "provider_org")
    if not title or not org:
        return None
    text = f"{title}. Қайда жүгіну керек: {org}."
    result = kk_service(code, "result")
    if result:
        text += f" Нәтижесі: {result[0].lower()}{result[1:].rstrip('.')}."
    return text


# ---------------------------------------------------------------------------
# AI texts


class StepText(BaseModel):
    service_id: ServiceId
    priority: Literal[1, 2, 3]
    rationale: str
    parent_explanation: str
    parent_explanation_kk: str


class PlanText(BaseModel):
    steps: list[StepText]


_SYSTEM = """Ты помогаешь куратору социальной службы Казахстана объяснить семье ребёнка с особыми
потребностями план шагов. Шаги, сроки и документы уже определены — ты их не меняешь, не добавляешь
и не убираешь. Верни ровно те service_id, что даны, по одному разу.

Для каждого шага:
- priority: 1 — сделать в первую очередь, 2 — важно, 3 — можно позже. Учитывай зависимости и срочность.
- rationale (для куратора, до 300 знаков): почему шаг в плане, со ссылкой на факты семьи.
- parent_explanation (для родителя, 1–3 предложения, до 450 знаков): простыми словами, на «вы»,
  что сделать и что это даст.
- parent_explanation_kk: тот же текст для родителя на казахском языке («сіз»), до 450 знаков.

Запрещено: называть или предполагать диагноз, степень, тяжесть или форму состояния ребёнка;
обещать результат или точные сроки — сроки только нормативные, не гарантия. Пиши по-русски."""


def _ai_prompt(steps: list[dict[str, Any]], facts: dict[str, Any]) -> str:
    visible = {k: facts[k] for k in _AI_VISIBLE_FACTS if facts.get(k) is not None}
    return json.dumps(
        {
            "family_facts": visible,
            "steps": [
                {
                    "service_id": s["service_id"],
                    "title": s["title"],
                    "why": SERVICES[s["service_id"]].get("why_short"),
                    "result": SERVICES[s["service_id"]].get("result"),
                    "rule": RULES[s["service_id"]].get("note"),
                    "depends_on": s["depends_on"],
                    "due_date": s["due_date"],
                    "deadline_note": s["deadline_note"],
                    "missing_documents": [d["title"] for d in s["documents"] if not d["on_hand"] and not d["from_step"]],
                }
                for s in steps
            ],
        },
        ensure_ascii=False,
    )


def _text_ok(text: StepText) -> bool:
    if not (0 < len(text.rationale) <= MAX_RATIONALE and 0 < len(text.parent_explanation) <= MAX_EXPLANATION):
        return False
    if not 0 < len(text.parent_explanation_kk) <= MAX_EXPLANATION:
        return False
    try:
        assert_no_diagnosis(text.rationale)
        assert_no_diagnosis(text.parent_explanation)
        assert_no_diagnosis(text.parent_explanation_kk)
    except DiagnosisInOutput as e:
        log.warning("AI text rejected for %s: %s", text.service_id.value, e)
        return False
    return True


def ai_texts(steps: list[dict[str, Any]], facts: dict[str, Any]) -> dict[str, StepText]:
    """AI texts per service code. Up to two attempts; steps still failing the checks are left out."""
    expected = [s["service_id"] for s in steps]
    accepted: dict[str, StepText] = {}
    prompt = _ai_prompt(steps, facts)
    for _ in range(2):
        result = llm.parse(_SYSTEM, prompt, PlanText)
        if result is None:
            return accepted
        codes = [t.service_id.value for t in result.steps]
        if sorted(codes) != sorted(expected):  # exactly the eligible set, no extras, no duplicates
            log.warning("AI returned services %s, expected %s", codes, expected)
            continue
        for text in result.steps:
            if text.service_id.value not in accepted and _text_ok(text):
                accepted[text.service_id.value] = text
        if len(accepted) == len(expected):
            break
    return accepted


# ---------------------------------------------------------------------------
# Plan


def build_plan(facts: dict[str, Any], start: date, *, use_ai: bool = True) -> dict[str, Any]:
    steps, undecided = build_steps(facts, start)
    _fill_due_dates(steps, facts, start)
    _fill_documents(steps, facts)

    texts = ai_texts(steps, facts) if use_ai and steps else {}
    for step in steps:
        text = texts.get(step["service_id"])
        if text:
            step["priority"] = text.priority
            step["rationale"], step["parent_explanation"] = text.rationale, text.parent_explanation
            step["parent_explanation_kk"] = text.parent_explanation_kk
            step["text_source"] = "ai"
        else:
            step["rationale"], step["parent_explanation"] = fallback_texts(step["service_id"])
            step["parent_explanation_kk"] = fallback_explanation_kk(step["service_id"])

    # Steps where waiting costs the family (a fixed date, a benefit not paid retroactively) stay first,
    # whatever priority the AI proposed.
    for step in steps:
        service = SERVICES[step["service_id"]]
        if service.get("deadline_type") == "calendar_date" or service.get("financial_risk"):
            step["priority"] = 1
    _propagate_priority(steps)
    sort_steps(steps)
    return {
        "start_date": start.isoformat(),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "generator": "ai" if texts else "fallback",
        "model": (os.getenv("OPENAI_MODEL") or llm.DEFAULT_MODEL) if texts else None,
        "steps": steps,
        "undecided": undecided,
        "urgent_reasons": red_flags(facts),
    }


def _propagate_priority(steps: list[dict[str, Any]]) -> None:
    """A prerequisite is as urgent as its most urgent dependent, so sorting never puts it after them."""
    by_code = {s["service_id"]: s for s in steps}
    for step in reversed([by_code[c] for c in dependency_order(set(by_code))]):
        for dep in step["depends_on"]:
            if dep in by_code:  # only within `steps`; steps already in the plan keep the curator's priority
                by_code[dep]["priority"] = min(by_code[dep]["priority"], step["priority"])


def sort_steps(steps: list[dict[str, Any]]) -> None:
    """Priority, then deadline; ties keep dependency order."""
    order = {code: i for i, code in enumerate(dependency_order({s["service_id"] for s in steps}))}
    steps.sort(key=lambda s: (s["priority"], s["due_date"], order[s["service_id"]]))


class StepExists(Exception):
    pass


def add_step(content: dict[str, Any], code: str, facts: dict[str, Any], today: date) -> list[str]:
    """Add a curator-chosen service and any prerequisites it still needs. Returns the added codes.

    Texts come from the catalog (no AI call); deadlines count from `today` or the prerequisites' deadlines.
    """
    existing = content["steps"]
    in_plan = {s["service_id"] for s in existing}
    if code in in_plan:
        raise StepExists(code)
    profile = build_profile(facts, today)
    new_codes = [c for c in with_prerequisites([code], profile) if c not in in_plan]
    all_codes = in_plan | set(new_codes)
    new_steps = [_step(c, facts, today, list(all_codes)) for c in new_codes]
    for step in new_steps:
        step["rationale"], step["parent_explanation"] = fallback_texts(step["service_id"])
        step["parent_explanation_kk"] = fallback_explanation_kk(step["service_id"])
        step["rationale"] = f"Добавлено куратором. {step['rationale']}"
    _fill_due_dates(new_steps, facts, today, prior=existing)
    _fill_documents(new_steps, facts, prior=existing)
    _propagate_priority(new_steps)
    steps = existing + new_steps
    sort_steps(steps)
    content["steps"] = steps
    content["undecided"] = [c for c in content.get("undecided", []) if c not in all_codes]
    content["removed"] = [r for r in content.get("removed", []) if r["service_id"] not in all_codes]
    return new_codes


class PlanNotReady(Exception):
    pass


def generate_plan(session: Session, case: Case, actor_user_id: int, *, regenerate: bool) -> Plan:
    """Create the case's plan (or rebuild it with `regenerate`). The case goes to `draft`."""
    plan = session.exec(select(Plan).where(Plan.case_id == case.id)).first()
    if plan and not regenerate:
        return plan
    if case.status == CaseStatus.interview and current_question(session, case, date.today())[0] is not None:
        raise PlanNotReady()

    content = build_plan(case.facts, case.created_at.date())
    now = datetime.now(UTC)
    if plan is None:
        plan = Plan(case_id=case.id, plan=content)
    else:
        plan.plan, plan.updated_at = content, now
    case.status = CaseStatus.draft
    session.add(plan)
    session.add(case)
    session.flush()
    session.add(
        Event(
            case_id=case.id,
            plan_id=plan.id,
            kind="plan_regenerated" if regenerate else "plan_generated",
            actor_user_id=actor_user_id,
            payload={"generator": content["generator"], "steps": [s["service_id"] for s in content["steps"]]},
        )
    )
    session.commit()
    session.refresh(plan)
    return plan
