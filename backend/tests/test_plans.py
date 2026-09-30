from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

import models
from db import get_session
from main import app
from services import overdue
from services.auth import get_current_user
from seed import CASE_A, CASE_B
from tests.test_interview import _run, session  # noqa: F401  (fixture)


@pytest.fixture
def api(session, monkeypatch):  # noqa: F811
    """A client plus a way to switch the logged-in user."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    current = {"id": 3}  # the curator; 1 is the parent, 2 another parent
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: session.get(models.User, current["id"])
    client = TestClient(app)
    client.login_as = lambda user_id: current.update(id=user_id)
    yield client
    app.dependency_overrides.clear()


def _planned_case(api, session, facts):  # noqa: F811
    case, _ = _run(session, facts)
    body = api.post(f"/cases/{case.id}/plan").json()
    return case, body


def _step(body, service_id):
    return next(s for s in body["plan"]["steps"] if s["service_id"] == service_id)


def _events(session, case_id):  # noqa: F811
    return session.exec(select(models.Event.kind).where(models.Event.case_id == case_id)).all()


def test_overdue_levels():
    assert [overdue.level(d) for d in (0, 1, 7, 8, 30)] == [0, 1, 1, 2, 2]
    step = {"status": "todo", "due_date": "2026-08-30"}
    assert overdue.overdue_days(step, date(2026, 9, 11)) == 12
    assert overdue.overdue_days({**step, "status": "done"}, date(2026, 9, 11)) == 0
    assert (overdue.LOAD_NORM_MIN, overdue.LOAD_NORM_MAX) == (10, 30)


def test_approval_gate(api, session):  # noqa: F811
    case, body = _planned_case(api, session, CASE_B)
    api.login_as(1)
    assert api.get(f"/parent/cases/{case.id}").status_code == 403  # not approved yet
    assert [c["id"] for c in api.get("/parent/cases").json()] == [case.id]

    api.login_as(2)
    assert api.get("/parent/cases").json() == []

    api.login_as(3)
    assert api.post(f"/plans/{body['id']}/approve").json()["case_status"] == "approved"

    api.login_as(2)
    assert api.get(f"/parent/cases/{case.id}").status_code == 403  # someone else's case

    api.login_as(1)
    r = api.get(f"/parent/cases/{case.id}")
    assert r.status_code == 200
    steps = r.json()["steps"]
    assert len(steps) == len(body["plan"]["steps"])
    assert all("rationale" not in s and s["parent_explanation"] for s in steps)
    assert _events(session, case.id) == ["plan_generated", "plan_approved"]

    # Regenerating sends the plan back to the curator.
    api.login_as(3)
    api.post(f"/cases/{case.id}/plan?regenerate=true")
    api.login_as(1)
    assert api.get(f"/parent/cases/{case.id}").status_code == 403


def test_step_edits(api, session):  # noqa: F811
    case, body = _planned_case(api, session, CASE_B)
    url = f"/plans/{body['id']}/steps"

    r = api.patch(f"{url}/PMPK_EXAM", json={"status": "done", "priority": 3, "due_date": "2026-10-01"})
    assert r.status_code == 200
    step = _step(r.json(), "PMPK_EXAM")
    assert (step["status"], step["priority"], step["due_date"]) == ("done", 3, "2026-10-01")
    assert step["deadline_note"] == "Срок изменён куратором"
    assert r.json()["plan"]["steps"][-1]["service_id"] == "PMPK_EXAM"  # resorted by priority
    event = session.exec(select(models.Event).where(models.Event.kind == "step_updated")).one()
    assert event.step_id == "PMPK_EXAM" and event.payload["changes"]["status"] == ["todo", "done"]

    assert api.patch(f"{url}/PMPK_EXAM", json={"priority": 4}).status_code == 422
    assert api.patch(f"{url}/PMPK_EXAM", json={"status": "lost"}).status_code == 422
    assert api.patch(f"{url}/PMPK_EXAM", json={}).status_code == 422
    assert api.patch(f"{url}/PMPK_EXAM", json={"due_date": None}).status_code == 422
    assert api.patch(f"{url}/NOPE", json={"status": "done"}).status_code == 404
    assert api.patch("/plans/999/steps/PMPK_EXAM", json={"status": "done"}).status_code == 404


def test_add_step_catalog_only(api, session):  # noqa: F811
    case, body = _planned_case(api, session, CASE_B)
    url = f"/plans/{body['id']}/steps?today=2026-09-01"

    assert api.post(url, json={"service_id": "ART_THERAPY"}).status_code == 422  # not in the catalog
    r = api.post(url, json={"service_id": "SSU_DAYCARE"})
    assert r.status_code == 201
    # ПМПК and МСЭ are already in the plan, so only the SSU chain is added, in dependency order.
    assert r.json()["added"] == ["SSU_NEEDS_ASSESSMENT", "SSU_DOCS", "SSU_PORTAL_CHOICE", "SSU_DAYCARE"]
    plan = r.json()["plan"]
    assert "SSU_DAYCARE" not in plan["undecided"]
    assessment = _step(r.json(), "SSU_NEEDS_ASSESSMENT")
    assert assessment["depends_on"] == ["MSE_DECISION", "PMPK_EXAM"]
    assert assessment["due_date"] > max(_step(r.json(), d)["due_date"] for d in assessment["depends_on"])
    assert assessment["rationale"].startswith("Добавлено куратором")
    assert api.post(url, json={"service_id": "SSU_DAYCARE"}).status_code == 409
    assert _events(session, case.id)[-1] == "step_added"


def test_overdue_list_and_escalation(api, session):  # noqa: F811
    case_a, body_a = _planned_case(api, session, CASE_A)
    case_b, body_b = _planned_case(api, session, CASE_B)
    school = _step(body_b, "SPECIAL_SCHOOL_ENROLL")
    due = date.fromisoformat(school["due_date"])

    # Case B's school step 12 days late (level 2); everything in B before it is late too.
    today = (due + timedelta(days=12)).isoformat()
    r = api.get(f"/cases?today={today}")
    assert r.status_code == 200
    by_id = {c["id"]: c for c in r.json()["cases"]}
    assert by_id[case_b.id]["worst_level"] == 2 and by_id[case_b.id]["overdue_count"] >= 1
    assert r.json()["cases"][0]["worst_level"] == max(c["worst_level"] for c in r.json()["cases"])
    assert r.json()["load"] == {**r.json()["load"], "active_cases": 2, "state": "below", "norm_max": 30}

    detail = api.get(f"/cases/{case_b.id}?today={today}").json()
    assert _step(detail["plan"], "SPECIAL_SCHOOL_ENROLL")["days_overdue"] == 12
    assert detail["answers"] and detail["facts"]["setting"] == "kindergarten_special"

    # Not late yet → no escalation.
    early = (due - timedelta(days=1)).isoformat()
    url_b = f"/plans/{body_b['id']}/steps/SPECIAL_SCHOOL_ENROLL/escalate"
    assert api.post(f"{url_b}?today={early}").status_code == 409
    r = api.post(f"{url_b}?today={today}")
    assert r.status_code == 200
    assert r.json()["overdue_level"] == 2 and "просрочка 12 дн." in r.json()["message"]
    assert r.json()["warning"] is None

    # The disability benefit escalation carries the catalog's "not paid retroactively" warning.
    benefit_due = date.fromisoformat(_step(body_a, "DISABILITY_BENEFIT")["due_date"])
    late = (benefit_due + timedelta(days=5)).isoformat()
    r = api.post(f"/plans/{body_a['id']}/steps/DISABILITY_BENEFIT/escalate?today={late}")
    assert r.json()["overdue_level"] == 1 and r.json()["warning"]
    assert "задним числом" in r.json()["message"].lower()
    assert _events(session, case_a.id)[-1] == "escalated"


def test_services_list(api):
    services = api.get("/services").json()
    assert len(services) == 21
    modes = {s["service_id"]: s["mode"] for s in services}
    assert modes["PMPK_APPEAL"] == "trigger" and modes["PMPK_EXAM"] == "direct"


def test_parent_marks_steps_done(api, session):  # noqa: F811
    case, body = _planned_case(api, session, CASE_B)
    url = f"/parent/cases/{case.id}/steps"
    school = _step(body, "SPECIAL_SCHOOL_ENROLL")
    late = (date.fromisoformat(school["due_date"]) + timedelta(days=12)).isoformat()

    api.login_as(1)
    assert api.patch(f"{url}/SPECIAL_SCHOOL_ENROLL", json={"done": True}).status_code == 403  # not approved yet
    api.login_as(3)
    assert api.patch(f"{url}/SPECIAL_SCHOOL_ENROLL", json={"done": True}).status_code == 403  # curator: not their route
    api.post(f"/plans/{body['id']}/approve")

    api.login_as(2)
    assert api.patch(f"{url}/SPECIAL_SCHOOL_ENROLL", json={"done": True}).status_code == 403  # someone else's case

    api.login_as(1)
    r = api.patch(f"{url}/SPECIAL_SCHOOL_ENROLL?today={late}", json={"done": True})
    assert r.status_code == 200
    step = next(s for s in r.json()["steps"] if s["step_id"] == "SPECIAL_SCHOOL_ENROLL")
    assert (step["status"], step["completed_by"], step["days_overdue"]) == ("done", "parent", 0)
    assert step["completed_at"] == date.today().isoformat()
    assert r.json()["overdue"]["steps_done"] == 1
    assert api.patch(f"{url}/SPECIAL_SCHOOL_ENROLL", json={"done": True}).status_code == 200  # idempotent
    assert api.patch(f"{url}/NOPE", json={"done": True}).status_code == 404
    assert api.patch(f"{url}/PMPK_EXAM", json={}).status_code == 422

    # The curator sees who marked it.
    api.login_as(3)
    detail = api.get(f"/cases/{case.id}").json()
    assert _step(detail["plan"], "SPECIAL_SCHOOL_ENROLL")["completed_by"] == "parent"
    events = session.exec(select(models.Event).where(models.Event.kind == "step_done_by_parent")).all()
    assert len(events) == 1 and events[0].actor_user_id == 1

    # Undo restores the previous status.
    api.login_as(1)
    r = api.patch(f"{url}/SPECIAL_SCHOOL_ENROLL", json={"done": False})
    step = next(s for s in r.json()["steps"] if s["step_id"] == "SPECIAL_SCHOOL_ENROLL")
    assert (step["status"], step["completed_by"], step["completed_at"]) == ("todo", None, None)
    assert _events(session, case.id)[-1] == "step_reopened_by_parent"

    # A step the curator marked done can't be reopened by the parent.
    api.login_as(3)
    r = api.patch(f"/plans/{body['id']}/steps/PMPK_EXAM", json={"status": "done"})
    assert _step(r.json(), "PMPK_EXAM")["completed_by"] == "curator"
    api.login_as(1)
    r = api.patch(f"{url}/PMPK_EXAM", json={"done": False})
    assert r.status_code == 409 and "куратор" in r.json()["detail"]

    # The curator moving a step out of "done" clears the mark.
    api.login_as(3)
    r = api.patch(f"/plans/{body['id']}/steps/PMPK_EXAM", json={"status": "in_progress"})
    assert _step(r.json(), "PMPK_EXAM")["completed_by"] is None
