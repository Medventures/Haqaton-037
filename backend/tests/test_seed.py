from datetime import date

from fastapi.testclient import TestClient
from sqlmodel import select

import models
import seed
from db import get_session
from main import app
from services.auth import get_current_user, verify_password
from tests.test_interview import session  # noqa: F401  (fixture)


def test_demo_date():
    assert seed.demo_date(date(2026, 9, 30)) == date(2026, 9, 11)
    assert seed.demo_date(date(2026, 9, 11)) == date(2026, 9, 11)
    assert seed.demo_date(date(2026, 3, 1)) == date(2025, 9, 11)


def test_seed(session):  # noqa: F811
    # A stale case from before, which the reset must remove; users are kept.
    session.add(models.Case(parent_user_id=1, label="old"))
    session.commit()

    parent, created, demo_today = seed.seed(session, date(2026, 9, 30))
    assert demo_today == date(2026, 9, 11)
    assert verify_password(seed.DEMO_PASSWORD, parent.password_hash)
    assert len(session.exec(select(models.User)).all()) == 3  # two test users + the demo parent
    assert [c.label for c in session.exec(select(models.Case)).all()] == ["Алихан, 3 года", "Амина, 6 лет"]

    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: parent
    try:
        client = TestClient(app)
        listing = client.get(f"/cases?today={demo_today}").json()["cases"]
        by_label = {c["label"]: c for c in listing}
        assert by_label["Алихан, 3 года"]["overdue_count"] == 1
        assert by_label["Алихан, 3 года"]["worst_level"] == 1
        assert by_label["Амина, 6 лет"]["overdue_count"] == 1
        assert by_label["Амина, 6 лет"]["worst_level"] == 2
        assert listing[0]["label"] == "Амина, 6 лет"  # worst first

        for case, _ in created:
            assert case.status == "approved"
            assert 8 <= len(session.exec(select(models.InterviewAnswer).where(
                models.InterviewAnswer.case_id == case.id)).all()) <= 12
            parent_view = client.get(f"/parent/cases/{case.id}?today={demo_today}").json()
            late = [(s["step_id"], s["days_overdue"]) for s in parent_view["steps"] if s["days_overdue"]]
            assert late == ([("PMPK_EXAM", 5)] if case.label.startswith("Алихан") else [("SPECIAL_SCHOOL_ENROLL", 12)])
            assert all(s["parent_explanation"] for s in parent_view["steps"])
    finally:
        app.dependency_overrides.clear()

    # Seeding twice gives the same two cases, not four.
    seed.seed(session, date(2026, 9, 30))
    assert len(session.exec(select(models.Case)).all()) == 2
