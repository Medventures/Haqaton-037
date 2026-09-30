from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

import models
from db import get_session
from main import app
from schemas import PlanContent
from services import planner
from services.auth import get_current_user
from services.catalog import SERVICES
from services.safety import contains_diagnosis
from seed import CASE_A, CASE_B
from tests.test_interview import _run, session  # noqa: F401  (fixture)

START = date(2026, 7, 15)  # a Wednesday


def _fake_ai(monkeypatch, *responses):
    """llm.parse returns these in turn; a callable response gets the steps' service ids."""
    calls = []

    def parse(system, prompt, schema):
        calls.append(prompt)
        return responses[min(len(calls), len(responses)) - 1]

    monkeypatch.setattr(planner.llm, "parse", parse)
    return calls


def _texts(codes, text="Сначала запишитесь на приём, это откроет следующие шаги.", priority=2,
           text_kk="Алдымен қабылдауға жазылыңыз, бұл келесі қадамдарды ашады."):
    return planner.PlanText(
        steps=[
            planner.StepText(service_id=c, priority=priority, rationale=f"Нужно: {c}", parent_explanation=text,
                             parent_explanation_kk=text_kk)
            for c in codes
        ]
    )


def _codes(facts):
    return [s["service_id"] for s in planner.build_steps(facts, START)[0]]


@pytest.mark.parametrize("facts", [CASE_A, CASE_B], ids=["case_a", "case_b"])
def test_fallback_plan(monkeypatch, facts):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    plan = planner.build_plan(facts, START)
    PlanContent.model_validate(plan)  # matches the API schema
    assert plan["generator"] == "fallback" and plan["model"] is None
    steps = plan["steps"]
    assert {s["service_id"] for s in steps} == set(_codes(facts))
    assert all(s["text_source"] == "fallback" and s["parent_explanation"] and s["rationale"] for s in steps)
    # Sorted by priority, then deadline, and a prerequisite never comes after its dependent.
    assert [(s["priority"], s["due_date"]) for s in steps] == sorted((s["priority"], s["due_date"]) for s in steps)
    position = {s["service_id"]: i for i, s in enumerate(steps)}
    for s in steps:
        assert all(position[d] < position[s["service_id"]] for d in s["depends_on"])
        assert all(s["due_date"] >= next(x for x in steps if x["service_id"] == d)["due_date"] for d in s["depends_on"])


def test_case_a_dates_and_documents():
    steps = {s["service_id"]: s for s in planner.build_plan(CASE_A, START, use_ai=False)["steps"]}
    assert steps["PMPK_EXAM"]["due_date"] == "2026-08-14"  # 30 calendar days
    assert steps["SPECIAL_SCHOOL_ENROLL"]["due_date"] == "2026-08-30"  # fixed date
    assert steps["MED_DIAGNOSIS_WAIT"]["due_date"] == "2026-09-13"  # 120 days minus 2 months already observed
    assert steps["VKK_REFERRAL"]["due_date"] == "2026-09-27"  # no statutory deadline: 14 days after its prerequisite
    assert steps["VKK_REFERRAL"]["deadline_note"] == planner.ASSIGNED_NOTE
    assert steps["MSE_DECISION"]["due_date"] == "2026-09-30"  # 3 working days from Sunday 27.09
    assert steps["DISABILITY_BENEFIT"]["warning"]  # benefit is not paid retroactively
    cert = next(d for d in steps["DISABILITY_BENEFIT"]["documents"] if d["doc_code"] == "DISABILITY_CERT")
    assert cert == {**cert, "on_hand": False, "from_step": "MSE_DECISION"}
    assert steps["PMPK_EXAM"]["legal_source"].endswith(", прил. 1")


def test_case_b_renews_pmpk_for_school():
    steps = {s["service_id"]: s for s in planner.build_plan(CASE_B, START, use_ai=False)["steps"]}
    pmpk = next(d for d in steps["SPECIAL_SCHOOL_ENROLL"]["documents"] if d["doc_code"] == "PMPK_CONCLUSION")
    assert pmpk["on_hand"] is False and pmpk["from_step"] == "PMPK_EXAM"


def test_working_days_and_fixed_dates():
    assert planner.add_working_days(date(2026, 7, 17), 1) == date(2026, 7, 20)  # Friday → Monday
    assert planner.add_working_days(date(2026, 7, 15), 0) == date(2026, 7, 15)
    assert planner.next_month_day(date(2026, 9, 1), "08-30") == date(2027, 8, 30)
    assert planner.next_month_day(date(2026, 8, 30), "08-30") == date(2026, 8, 30)


def test_fixed_date_moves_to_next_year_after_prerequisite():
    steps = {s["service_id"]: s for s in planner.build_plan(CASE_A, date(2026, 8, 10), use_ai=False)["steps"]}
    assert steps["PMPK_EXAM"]["due_date"] == "2026-09-09"
    assert steps["SPECIAL_SCHOOL_ENROLL"]["due_date"] == "2027-08-30"


def test_ai_texts_used(monkeypatch):
    calls = _fake_ai(monkeypatch, _texts(_codes(CASE_B), priority=3))
    plan = planner.build_plan(CASE_B, START)
    assert len(calls) == 1 and plan["generator"] == "ai"
    assert all(s["text_source"] == "ai" for s in plan["steps"])
    priority = {s["service_id"]: s["priority"] for s in plan["steps"]}
    # The fixed-date step stays first, and so does the ПМПК it depends on; the rest follow the AI.
    assert priority == {"SPECIAL_SCHOOL_ENROLL": 1, "PMPK_EXAM": 1, "VKK_REFERRAL": 3, "MSE_DECISION": 3}
    # Health answers never reach the AI.
    assert "months_since_diagnosis" not in calls[0] and "self_care" not in calls[0]


def test_ai_must_return_exactly_the_eligible_set(monkeypatch):
    codes = _codes(CASE_B)
    extra = _texts([*codes, "SSU_RESIDENTIAL"])
    missing = _texts(codes[:-1])
    calls = _fake_ai(monkeypatch, extra, missing)
    plan = planner.build_plan(CASE_B, START)
    assert len(calls) == 2 and plan["generator"] == "fallback"
    assert {s["service_id"] for s in plan["steps"]} == set(codes)


def test_diagnosis_in_ai_text_retries_then_falls_back(monkeypatch):
    codes = _codes(CASE_B)
    bad = _texts(codes, text="У ребёнка аутизм тяжёлой степени, поэтому нужна школа.")
    calls = _fake_ai(monkeypatch, bad, bad)
    plan = planner.build_plan(CASE_B, START)
    assert len(calls) == 2 and all(s["text_source"] == "fallback" for s in plan["steps"])
    assert not any(contains_diagnosis(s["parent_explanation"]) for s in plan["steps"])

    good = _texts(codes)
    calls = _fake_ai(monkeypatch, bad, good)
    assert planner.build_plan(CASE_B, START)["generator"] == "ai" and len(calls) == 2


def test_kazakh_diagnosis_in_ai_text_falls_back(monkeypatch):
    codes = _codes(CASE_B)
    bad = _texts(codes, text_kk="Балада аутизм, ауыр дәрежесі.")
    calls = _fake_ai(monkeypatch, bad, bad)
    plan = planner.build_plan(CASE_B, START)
    assert len(calls) == 2 and all(s["text_source"] == "fallback" for s in plan["steps"])
    assert not any("аутизм" in (s["parent_explanation_kk"] or "") for s in plan["steps"])


def test_ai_kazakh_text_is_kept(monkeypatch):
    _fake_ai(monkeypatch, _texts(_codes(CASE_B)))
    plan = planner.build_plan(CASE_B, START)
    assert all(s["parent_explanation_kk"].startswith("Алдымен") for s in plan["steps"])
    assert all(s["deadline_note_kk"] for s in plan["steps"])


def test_fallback_parent_texts_have_no_team_notes():
    for code in SERVICES:
        _, explanation = planner.fallback_texts(code)
        assert "демонстрац" not in explanation and explanation.startswith(SERVICES[code]["title_ru"])


def test_plan_endpoint(session, monkeypatch):  # noqa: F811
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app.dependency_overrides[get_session] = lambda: session
    current = {"id": 3}  # curator
    app.dependency_overrides[get_current_user] = lambda: session.get(models.User, current["id"])
    try:
        client = TestClient(app)
        unfinished = models.Case(parent_user_id=1, label="x", created_at=datetime(2026, 7, 15, tzinfo=UTC))
        session.add(unfinished)
        session.commit()
        assert client.post(f"/cases/{unfinished.id}/plan").status_code == 409
        assert client.post("/cases/9999/plan").status_code == 404

        case, _ = _run(session, CASE_B)
        r = client.post(f"/cases/{case.id}/plan")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["case_status"] == "draft" and body["plan"]["generator"] == "fallback"
        assert {s["service_id"] for s in body["plan"]["steps"]} == set(_codes(CASE_B))

        # Without regenerate the stored plan comes back unchanged; with it, a new one is built.
        assert client.post(f"/cases/{case.id}/plan").json()["plan"] == body["plan"]
        assert client.post(f"/cases/{case.id}/plan?regenerate=true").status_code == 200
        kinds = session.exec(select(models.Event.kind).where(models.Event.case_id == case.id)).all()
        assert kinds == ["plan_generated", "plan_regenerated"]
    finally:
        app.dependency_overrides.clear()
