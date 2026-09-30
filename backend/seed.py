"""Demo data: resets the case tables (users are kept), then creates a demo parent with two approved cases
and a demo curator (curators are normally created by an admin with scripts/create_curator.py).

Run from backend/:
    python seed.py            # local SQLite; asks for --yes on any other database
    python seed.py --yes      # e.g. Supabase

Overdue is shown against the demo date (the curator's «Симулировать дату», passed as ?today=):
  Case A «Алихан, 3 года» — the ПМПК step is 5 days overdue.
  Case B «Амина, 6 лет»   — school enrolment (30 August) is 12 days overdue.
The school deadline is a fixed date, so the demo date is 11 September.
Plans are built by the rule-based fallback, so seeding never calls OpenAI.
"""

import argparse
import sys
from datetime import UTC, date, datetime, time, timedelta
from itertools import combinations
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from sqlmodel import Session, delete, select  # noqa: E402

from db import IS_SQLITE, create_db_and_tables, engine  # noqa: E402
from models import Case, CaseStatus, Event, InterviewAnswer, Plan, User, UserRole  # noqa: E402
from schemas import AnswerIn  # noqa: E402
from services import catalog, interview, planner  # noqa: E402
from services.auth import hash_password  # noqa: E402
from services.phone import normalize_phone  # noqa: E402

DEMO_PHONE = normalize_phone("+7 700 000 00 01")
DEMO_CURATOR_PHONE = normalize_phone("+7 700 000 00 02")
DEMO_PASSWORD = "demo12345"  # both demo accounts

# Case A «Алихан, 3 года»: doctor's conclusion, no ПМПК, no disability yet, not in kindergarten.
CASE_A = {
    "age_months": 36,
    "region": "Караганда",
    "has_doctor_conclusion": True,
    "setting": "home",
    "documents_on_hand": [],
    "seeking_disability": True,
    "months_since_diagnosis": 2,
    "goal": "kindergarten",
    "current_support": [],
    "has_curator": "none",
}

# Case B «Амина, 6 лет»: disability registered, special kindergarten group, starting school next year.
CASE_B = {
    "age_months": 72,
    "region": "Караганда",
    "has_doctor_conclusion": True,
    "setting": "kindergarten_special",
    "documents_on_hand": ["PMPK_CONCLUSION", "DISABILITY_CERT", "IPR"],
    "goal": "school",
    "current_support": ["KPPK"],
    "benefits_received": ["DISABILITY_BENEFIT", "SPECIAL_STATE_BENEFIT"],
    "has_curator": "social_worker",
}

# (label, facts, step that is late, days late, days from case start to the demo date)
DEMO_CASES = [
    ("Алихан, 3 года", CASE_A, "PMPK_EXAM", 5, 35),  # ПМПК: 30 calendar days from the start
    ("Амина, 6 лет", CASE_B, "SPECIAL_SCHOOL_ENROLL", 12, 60),  # started mid-July, ПМПК done before 30.08
]


def demo_date(today: date) -> date:
    """The most recent 11 September: 12 days after the 30 August school deadline."""
    this_year = date(today.year, 9, 11)
    return this_year if today >= this_year else date(today.year - 1, 9, 11)


def answer_for(question: interview.Question, facts: dict[str, Any]) -> AnswerIn:
    """What a parent with these facts would click; «Не знаю» for anything not in `facts`."""
    value = facts.get(question.slot)
    if value is None:
        return AnswerIn(slot=question.slot, dont_know=True)
    match question.kind:
        case "age" | "months":
            return AnswerIn(slot=question.slot, value=value)
        case "text":
            return AnswerIn(slot=question.slot, text=value)
        case "choice":
            options = range(len(question.options))
            index = next(i for i in options if catalog.option_value(question.group_id, i) == value)
            return AnswerIn(slot=question.slot, option=index)
        case "multi":
            n = len(question.options)
            for size in range(1, n + 1):
                for combo in combinations(range(n), size):
                    if {v for i in combo for v in catalog.option_value(question.group_id, i)} == set(value):
                        return AnswerIn(slot=question.slot, options=list(combo))
    raise ValueError(f"no answer for {question.slot}={value!r}")


def run_interview(session: Session, case: Case, facts: dict[str, Any], today: date) -> int:
    """Answer the real interview as this family would. Returns the number of questions asked."""
    asked = 0
    while (question := interview.current_question(session, case, today)[0]) is not None:
        interview.submit_answer(session, case, answer_for(question, facts), today)
        asked += 1
    return asked


def _demo_user(session: Session, phone: str, first_name: str, role: UserRole) -> User:
    user = session.exec(select(User).where(User.phone == phone)).first()
    if user is None:
        user = User(last_name="Демо", first_name=first_name, phone=phone, password_hash="", role=role)
    elif user.role != role:  # roles never switch, not even for the demo numbers
        raise ValueError(f"+{phone} is already a {user.role} account; the demo needs it as {role}")
    user.password_hash = hash_password(DEMO_PASSWORD)  # always the documented demo password
    session.add(user)
    session.flush()
    return user


def reset_cases(session: Session) -> None:
    for table in (Event, Plan, InterviewAnswer, Case):  # children first (foreign keys)
        session.exec(delete(table))
    session.flush()


def seed(session: Session, today: date) -> tuple[User, list[tuple[Case, Plan]], date]:
    demo_today = demo_date(today)
    reset_cases(session)
    parent = _demo_user(session, DEMO_PHONE, "Родитель", UserRole.parent)
    _demo_user(session, DEMO_CURATOR_PHONE, "Куратор", UserRole.curator)

    created = []
    for label, facts, late_step, days_late, start_offset in DEMO_CASES:
        start = demo_today - timedelta(days=start_offset)
        case = Case(
            parent_user_id=parent.id,
            label=label,
            created_at=datetime.combine(start, time(10, 0), tzinfo=UTC),
        )
        session.add(case)
        session.commit()
        session.refresh(case)
        run_interview(session, case, facts, start)

        content = planner.build_plan(case.facts, start, use_ai=False)
        late = next(s for s in content["steps"] if s["service_id"] == late_step)
        late_by = (demo_today - date.fromisoformat(late["due_date"])).days
        assert late_by == days_late, f"{label}: {late_step} is {late_by} days late, expected {days_late}"
        # Everything else due before the demo date is done, so exactly one step is overdue.
        for step in content["steps"]:
            if step is not late and date.fromisoformat(step["due_date"]) < demo_today:
                step.update(status="done", completed_by="curator", completed_at=step["due_date"])

        plan = Plan(case_id=case.id, plan=content)
        case.status = CaseStatus.approved
        session.add_all([plan, case])
        session.flush()
        session.add_all(
            [
                Event(case_id=case.id, plan_id=plan.id, kind="plan_generated", payload={"generator": "fallback"}),
                Event(case_id=case.id, plan_id=plan.id, kind="plan_approved", payload={"seed": True}),
            ]
        )
        session.commit()
        session.refresh(plan)
        created.append((case, plan))
    return parent, created, demo_today


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="confirm resetting cases on a non-SQLite database")
    args = parser.parse_args()
    if not IS_SQLITE and not args.yes:
        sys.exit("This deletes every case, plan, answer and event (users are kept). Re-run with --yes.")

    create_db_and_tables()
    with Session(engine) as session:
        parent, created, demo_today = seed(session, date.today())
        print(f"Demo parent:  phone +{parent.phone}, password {DEMO_PASSWORD}")
        print(f"Demo curator: phone +{DEMO_CURATOR_PHONE}, password {DEMO_PASSWORD}")
        for case, plan in created:
            steps = plan.plan["steps"]
            late = [s["service_id"] for s in steps if s["status"] != "done" and s["due_date"] < demo_today.isoformat()]
            print(f"  case {case.id} «{case.label}»: {len(steps)} steps, approved, overdue on {demo_today}: {late}")
        print(f"Curator view: pass ?today={demo_today} («Симулировать дату»).")


if __name__ == "__main__":
    main()
