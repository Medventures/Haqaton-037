import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlmodel import select

import db
import models
from db import get_session
from main import app
from schemas import RegisterIn
from scripts.create_curator import CuratorError, upsert_curator
from seed import CASE_B
from services import auth, otp
from services.auth import get_current_user, verify_password
from tests.test_interview import _run, session  # noqa: F401  (fixture)


@pytest.fixture
def client(session, monkeypatch):  # noqa: F811
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    current = {"id": 1}
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: session.get(models.User, current["id"])
    c = TestClient(app)
    c.login_as = lambda user_id: current.update(id=user_id)
    yield c
    app.dependency_overrides.clear()


def test_parent_cannot_use_curator_endpoints(client, session):  # noqa: F811
    case, _ = _run(session, CASE_B)
    client.login_as(3)
    plan_id = client.post(f"/cases/{case.id}/plan").json()["id"]

    client.login_as(1)  # the case's own parent
    for method, url in [
        ("get", "/cases"),
        ("get", f"/cases/{case.id}"),
        ("post", f"/cases/{case.id}/plan"),
        ("post", f"/plans/{plan_id}/approve"),
        ("patch", f"/plans/{plan_id}/steps/PMPK_EXAM"),
        ("post", f"/plans/{plan_id}/steps"),
        ("post", f"/plans/{plan_id}/steps/PMPK_EXAM/escalate"),
    ]:
        body = {} if method == "get" else {"json": {"status": "done", "service_id": "SSU_HOME"}}
        r = getattr(client, method)(url, **body)
        assert r.status_code == 403, (method, url, r.status_code)
        assert r.json()["detail"] == "Доступно только куратору"


def test_curator_cannot_use_parent_endpoints(client, session):  # noqa: F811
    case, _ = _run(session, CASE_B)
    client.login_as(3)
    for method, url in [
        ("post", "/cases"),
        ("get", f"/cases/{case.id}/interview"),
        ("post", f"/cases/{case.id}/answers"),
        ("get", "/parent/cases"),
        ("get", f"/parent/cases/{case.id}"),
        ("post", f"/parent/cases/{case.id}/plan"),
    ]:
        body = {} if method == "get" else {"json": {"label": "x", "slot": "region", "text": "x"}}
        r = getattr(client, method)(url, **body)
        assert r.status_code == 403, (method, url, r.status_code)
        assert r.json()["detail"] == "Доступно только родителю"


def test_parent_submits_interview_without_seeing_the_plan(client, session):  # noqa: F811
    unfinished = models.Case(parent_user_id=1, label="x")
    session.add(unfinished)
    session.commit()
    assert client.post(f"/parent/cases/{unfinished.id}/plan").status_code == 409

    case, _ = _run(session, CASE_B)
    r = client.post(f"/parent/cases/{case.id}/plan")
    assert r.status_code == 200
    assert r.json()["status"] == "draft" and "plan" not in r.json()
    client.login_as(2)
    assert client.post(f"/parent/cases/{case.id}/plan").status_code == 403  # not their case


def test_me_returns_role(client, session):  # noqa: F811
    assert client.get("/auth/me").json()["role"] == "parent"
    client.login_as(3)
    assert client.get("/auth/me").json()["role"] == "curator"


def test_registration_always_creates_a_parent(session, monkeypatch):  # noqa: F811
    monkeypatch.setattr(otp, "verify_code", lambda session, phone, code: None)
    data = RegisterIn(phone="+7 702 111 22 33", last_name="Н", first_name="Р", password="password1", code="123456")
    assert auth.register(session, data).role == "parent"
    # Extra fields such as a role are not part of the registration schema.
    assert "role" not in RegisterIn.model_fields


def test_create_curator(session):  # noqa: F811
    user, created = upsert_curator(session, "+7 705 000 00 09", "Иванова", "Айгерим", None, "secret123")
    assert created and user.role == "curator" and user.phone == "77050000009"
    user, created = upsert_curator(session, "87050000009", "Иванова", "Айгерим", None, "newpass123")
    assert not created and verify_password("newpass123", user.password_hash)

    parent = models.User(last_name="Р", first_name="Р", phone="77010000011", password_hash="x")
    session.add(parent)
    session.commit()
    with pytest.raises(CuratorError, match="родитель"):  # a parent's number never becomes a curator
        upsert_curator(session, "+7 701 000 00 11", "Тест", "Родитель", None, "secret123")
    session.refresh(parent)
    assert parent.role == "parent" and parent.password_hash == "x"
    with pytest.raises(CuratorError, match="Пароль"):
        upsert_curator(session, "+7 705 000 00 08", "А", "Б", None, "short")
    assert session.exec(select(models.User).where(models.User.phone == "77050000008")).first() is None


def test_migration_adds_role_to_existing_users_table(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:  # the users table as it was before roles
        conn.execute(text(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, last_name VARCHAR(100) NOT NULL, first_name VARCHAR(100) "
            "NOT NULL, middle_name VARCHAR(100), phone VARCHAR(20) NOT NULL UNIQUE, password_hash VARCHAR(255) NOT NULL)"
        ))
        conn.execute(text("INSERT INTO users VALUES (1, 'А', 'Б', NULL, '77010000009', 'x')"))
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "IS_SQLITE", True)
    db.create_db_and_tables()
    db.create_db_and_tables()  # idempotent
    assert "role" in {c["name"] for c in inspect(engine).get_columns("users")}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT role FROM users")).scalar() == "parent"
