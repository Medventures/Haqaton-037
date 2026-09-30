from datetime import date

import pytest

from scripts import validate_catalog
from services import catalog
from services.eligibility import (
    build_profile,
    eligible,
    evaluate,
    question_applies,
    referenced_facts,
    select_services,
    service_condition,
    with_prerequisites,
)

TODAY = date(2026, 9, 30)

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


def _assert_dependency_order(codes: list[str]) -> None:
    for i, code in enumerate(codes):
        for dep in catalog.SERVICES[code]["depends_on"]:
            if dep in codes:
                assert codes.index(dep) < i, f"{dep} must come before {code}"


def test_catalog_is_consistent():
    assert validate_catalog.validate() == []


def test_validator_catches_unknown_fact(monkeypatch):
    broken = {**catalog.RULES, "PMPK_EXAM": {"mode": "direct", "when": {"fact": "diagnosis", "eq": "x"}}}
    monkeypatch.setattr(validate_catalog, "RULES", broken)
    assert any("unknown fact 'diagnosis'" in e for e in validate_catalog.validate())


def test_enums_match_catalog():
    assert {s.value for s in catalog.ServiceId} == set(catalog.SERVICES)
    assert {f.value for f in catalog.FactKey} == set(catalog.FACTS)
    assert "has_doctor_conclusion" in {s.value for s in catalog.SlotId}


def test_no_diagnosis_fact_exists():
    assert not any("diagnos" in f and f != "months_since_diagnosis" for f in catalog.FACTS)


@pytest.mark.parametrize(
    ("cond", "expected"),
    [
        ({"all": [{"fact": "a", "eq": 1}, {"fact": "missing", "eq": 1}]}, None),
        ({"all": [{"fact": "a", "eq": 2}, {"fact": "missing", "eq": 1}]}, False),
        ({"any": [{"fact": "a", "eq": 1}, {"fact": "missing", "eq": 1}]}, True),
        ({"any": [{"fact": "a", "eq": 2}, {"fact": "missing", "eq": 1}]}, None),
        ({"not": {"fact": "missing", "eq": 1}}, None),
        ({"fact": "s", "contains_any": ["x", "z"]}, True),
        ({"fact": "s", "contains": "z"}, False),
    ],
)
def test_three_valued_logic(cond, expected):
    assert evaluate(cond, {"a": 1, "s": ["x", "y"]}) is expected


def test_derived_facts():
    p = build_profile({"age_months": 72, "setting": "kindergarten_special", "documents_on_hand": ["IPR"]}, TODAY)
    assert p["has_ipr"] is True
    assert p["has_disability_cert"] is False
    assert p["school_transition"] is True
    assert p["month_now"] == 9

    unknown_docs = build_profile({"age_months": 30}, TODAY)
    assert unknown_docs["has_disability_cert"] is None
    assert unknown_docs["school_transition"] is False  # too young, whatever the setting


def test_case_a_services():
    sel = select_services(build_profile(CASE_A, TODAY))
    _assert_dependency_order(sel.selected)
    assert set(sel.selected) == {
        "PMPK_EXAM",
        "REHAB_ENROLL",
        "SPECIAL_SCHOOL_ENROLL",
        "MED_DIAGNOSIS_WAIT",
        "VKK_REFERRAL",
        "MSE_DECISION",
        "DISABILITY_BENEFIT",
        "SPECIAL_STATE_BENEFIT",
        "SSU_HEALTH_SOCIAL_WORKER",
    }
    assert sel.undecided == ["SSU_DAYCARE", "SSU_HOME"]  # wants_ssu was never asked


def test_case_b_services():
    sel = select_services(build_profile(CASE_B, TODAY))
    # ПМПК for school, IPR update via МСЭ (needs a fresh ВКК referral), school enrollment.
    # The 4-month observation step is skipped because the disability is already registered.
    _assert_dependency_order(sel.selected)
    assert set(sel.selected) == {"PMPK_EXAM", "SPECIAL_SCHOOL_ENROLL", "VKK_REFERRAL", "MSE_DECISION"}
    assert sel.undecided == ["SSU_DAYCARE", "SSU_HOME"]


def test_unknown_facts_leave_services_undecided():
    p = build_profile({"age_months": 48}, TODAY)
    assert eligible("PMPK_EXAM", p) is None
    assert eligible("REHAB_ENROLL", p) is None


def test_catalog_age_limits_apply():
    profile = build_profile({**CASE_B, "age_months": 12, "wants_ssu": "daycare"}, TODAY)
    assert eligible("SSU_DAYCARE", profile) is False  # SSU day care starts at 18 months


def test_trigger_and_prerequisite_services_never_apply_alone():
    p = build_profile(CASE_A, TODAY)
    for code in ("PMPK_APPEAL", "SSU_RESIDENTIAL", "TSR_DOCS", "VKK_REFERRAL"):
        assert eligible(code, p) is False


def test_curator_added_service_pulls_in_its_chain():
    p = build_profile(CASE_B, TODAY)
    # МСЭ and ПМПК are already done (documents on hand), so only the SSU chain is added.
    assert with_prerequisites(["SSU_DAYCARE"], p) == [
        "SSU_NEEDS_ASSESSMENT",
        "SSU_DOCS",
        "SSU_PORTAL_CHOICE",
        "SSU_DAYCARE",
    ]


def test_question_applicability():
    assert question_applies("seeking_disability.all", build_profile({"documents_on_hand": []}, TODAY)) is True
    assert question_applies("seeking_disability.all", build_profile(CASE_B, TODAY)) is False
    assert question_applies("seeking_disability.all", build_profile({}, TODAY)) is None
    assert question_applies("goal.preschool", build_profile({"age_months": 48}, TODAY)) is True


def test_referenced_facts_expand_derived():
    facts = referenced_facts(service_condition("PMPK_EXAM"))
    assert facts == {"documents_on_hand", "age_months", "setting"}


def test_option_values_and_dont_know():
    assert catalog.option_value("documents.older", 1) == ["DISABILITY_CERT"]
    assert catalog.option_value("seeking_disability.all", 3) is None
    assert catalog.dont_know_value("goal") == "unknown"
    assert catalog.dont_know_value("setting") is None


def test_legal_source_text():
    assert catalog.legal_source_text("PMPK_EXAM").endswith(", прил. 1")
