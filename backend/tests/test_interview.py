from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import models
from db import get_session
from main import app
from schemas import AnswerIn
from seed import CASE_A, CASE_B, answer_for
from services import catalog, interview
from services.auth import get_current_user
from services.eligibility import build_profile, select_services

TODAY = date(2026, 9, 30)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(models.User(id=1, last_name="Тест", first_name="Родитель", phone="+77010000001", password_hash="x"))
        s.add(models.User(id=2, last_name="Чужой", first_name="Родитель", phone="+77010000002", password_hash="x"))
        s.commit()
        yield s


def _run(session: Session, target: dict[str, Any]) -> tuple[models.Case, list[str]]:
    case = models.Case(parent_user_id=1, label="test")
    session.add(case)
    session.commit()
    session.refresh(case)
    asked = []
    while (q := interview.current_question(session, case, TODAY)[0]) is not None:
        asked.append(q.slot)
        interview.submit_answer(session, case, answer_for(q, target), TODAY)
    return case, asked


@pytest.mark.parametrize("target", [CASE_A, CASE_B], ids=["case_a", "case_b"])
def test_scripted_interview(session, target):
    case, asked = _run(session, target)
    assert interview.MIN_QUESTIONS <= len(asked) <= interview.MAX_QUESTIONS
    assert asked[:5] == interview.FIXED_SLOTS
    assert len(set(asked)) == len(asked)
    # Every fact the interview asked about is saved as the parent answered it.
    for slot in asked:
        assert case.facts.get(slot) == target.get(slot), slot
    # The interview asked enough to reach the same plan as the full fact set.
    got = select_services(build_profile(case.facts, TODAY)).selected
    assert got == select_services(build_profile(target, TODAY)).selected
    assert len(interview.answers_for(session, case)) == len(asked)


def test_dont_know_everything_still_asks_minimum(session):
    _, asked = _run(session, {})
    assert interview.MIN_QUESTIONS <= len(asked) <= interview.MAX_QUESTIONS


def test_variant_text_is_stable_per_case():
    group = catalog.QUESTION_GROUPS["documents.older"]
    assert interview.variant_text(7, group) == interview.variant_text(7, group)
    assert {interview.variant_text(i, group) for i in range(30)} == set(group["variants"])


@pytest.mark.parametrize(
    ("text", "months"),
    [("3 года 2 месяца", 38), ("18 мес", 18), ("4", 48), ("12.05.2022", 52), ("2 жас", 24), ("завтра", None)],
)
def test_parse_age(text, months):
    assert interview.parse_age_months(text, TODAY) == months


@pytest.mark.parametrize(("text", "months"), [("полгода", 6), ("полтора года", 18), ("3", 3), ("год назад", 12)])
def test_parse_duration(text, months):
    assert interview.parse_duration_months(text, default_unit="months") == months


def test_free_text_without_ai(session, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    q = interview.next_question(1, {"age_months": 36, "region": "Караганда"}, ["age_months", "region"], TODAY)
    assert q.slot == "has_doctor_conclusion"
    parsed, _ = interview.parse_answer(q, AnswerIn(slot=q.slot, text="да, есть"), set(), TODAY)
    assert parsed == {"has_doctor_conclusion": True}
    parsed, _ = interview.parse_answer(q, AnswerIn(slot=q.slot, text="не знаю"), set(), TODAY)
    assert parsed == {"has_doctor_conclusion": None}
    with pytest.raises(interview.AnswerError):
        interview.parse_answer(q, AnswerIn(slot=q.slot, text="врач сказал подождать"), set(), TODAY)


def test_ai_extraction_is_checked_against_catalog(monkeypatch):
    fake = interview.Extraction(
        facts=[
            interview.ExtractedFact(fact="has_doctor_conclusion", value=True),
            interview.ExtractedFact(fact="seeking_disability", value=True),
            interview.ExtractedFact(fact="setting", value="spaceship"),  # not in the vocabulary
            interview.ExtractedFact(fact="self_care", value=2),  # scale, not this question
            interview.ExtractedFact(fact="region", value="аутизм"),  # diagnosis filter
            interview.ExtractedFact(fact="age_months", value=40),  # already known
        ]
    )
    monkeypatch.setattr(interview.llm, "parse", lambda *a: fake)
    q = interview.next_question(1, {"age_months": 36, "region": "Караганда"}, ["age_months", "region"], TODAY)
    parsed, _ = interview.parse_answer(
        q, AnswerIn(slot=q.slot, text="заключение есть, оформляем инвалидность"), {"age_months"}, TODAY
    )
    assert parsed == {"has_doctor_conclusion": True, "seeking_disability": True}


def test_api_flow(session):
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: session.get(models.User, 1)
    try:
        client = TestClient(app)
        r = client.post("/cases", json={"label": "Алихан, 3 года"})
        assert r.status_code == 201
        body = r.json()
        case_id, q = body["case"]["id"], body["question"]
        assert body["case"]["status"] == "interview" and q["slot"] == "age_months"
        assert q["text"] in catalog.QUESTION_GROUPS["age.all"]["variants"]

        r = client.post(f"/cases/{case_id}/answers", json={"slot": "region", "text": "Караганда"})
        assert r.status_code == 409  # not the current question
        r = client.post(f"/cases/{case_id}/answers", json={"slot": "age_months", "value": 36, "text": "3"})
        assert r.status_code == 422  # two answers at once
        r = client.post(f"/cases/{case_id}/answers", json={"slot": "age_months", "text": "3 года"})
        assert r.status_code == 200 and r.json()["answered"] == 1
        assert r.json()["question"]["slot"] == "region"
        assert client.get(f"/cases/{case_id}/interview").json()["question"] == r.json()["question"]

        app.dependency_overrides[get_current_user] = lambda: session.get(models.User, 2)
        assert client.get(f"/cases/{case_id}/interview").status_code == 403
        assert client.get("/cases/9999/interview").status_code == 404
    finally:
        app.dependency_overrides.clear()
