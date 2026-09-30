"""Check that services, rules, facts and questions agree with each other.

Run from backend/: python scripts/validate_catalog.py  (exit code 1 on errors)
"""

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.catalog import (  # noqa: E402
    DERIVED,
    DOCUMENTS,
    FACTS,
    LEGAL_SOURCES,
    OPTION_VALUES,
    QUESTION_GROUPS,
    RULES,
    SERVICES,
    is_valid_fact_value,
)
from services.eligibility import applies_when_condition, dependency_order  # noqa: E402

MODES = {"direct", "prerequisite", "trigger"}
OPERATORS = {"eq", "ne", "in", "gte", "gt", "lt", "lte", "contains", "contains_any"}
NO_OPTION_TYPES = {"age", "text", "months", "date", "number"}


def _check_condition(cond: Any, where: str, errors: list[str]) -> None:
    if not isinstance(cond, dict):
        errors.append(f"{where}: condition must be an object, got {cond!r}")
        return
    if "all" in cond or "any" in cond:
        for c in cond.get("all", cond.get("any")):
            _check_condition(c, where, errors)
        return
    if "not" in cond:
        _check_condition(cond["not"], where, errors)
        return
    fact = cond.get("fact")
    ops = [k for k in cond if k != "fact"]
    if fact not in FACTS and fact not in DERIVED:
        errors.append(f"{where}: unknown fact {fact!r}")
        return
    if len(ops) != 1 or ops[0] not in OPERATORS:
        errors.append(f"{where}: expected exactly one operator of {sorted(OPERATORS)}, got {ops}")
        return
    if fact in DERIVED:
        return  # derived values are bools or computed numbers
    op, arg = ops[0], cond[ops[0]]
    is_set = FACTS[fact]["type"] == "set"
    if (op in ("contains", "contains_any")) != is_set:
        errors.append(f"{where}: operator {op!r} does not fit fact {fact!r}")
        return
    # Wrap single elements of a set fact as one-element sets so is_valid_fact_value can check them.
    if op == "in":
        candidates = arg
    elif op == "contains":
        candidates = [[arg]]
    elif op == "contains_any":
        candidates = [[a] for a in arg]
    else:
        candidates = [arg]
    for v in candidates:
        if not is_valid_fact_value(fact, v):
            errors.append(f"{where}: value {v!r} is not valid for fact {fact!r}")


def validate() -> list[str]:
    errors: list[str] = []

    # Services ↔ documents, legal sources, dependencies
    for code, s in SERVICES.items():
        for key in ("documents_required", "documents_optional", "documents_on_request", "produces"):
            for doc in s.get(key) or []:
                if doc not in DOCUMENTS:
                    errors.append(f"services.{code}.{key}: unknown document {doc!r}")
        if s["legal_source"] not in LEGAL_SOURCES:
            errors.append(f"services.{code}: unknown legal_source {s['legal_source']!r}")
        for dep in s["depends_on"]:
            if dep not in SERVICES:
                errors.append(f"services.{code}.depends_on: unknown service {dep!r}")
    try:
        dependency_order(set(SERVICES))
    except ValueError as e:
        errors.append(f"services: {e}")

    # Rules: one entry per service, valid modes and conditions
    for code in SERVICES.keys() - RULES.keys():
        errors.append(f"rules: missing entry for service {code!r}")
    for code, rule in RULES.items():
        where = f"rules.{code}"
        if code not in SERVICES:
            errors.append(f"{where}: not a catalog service")
            continue
        mode = rule.get("mode")
        if mode not in MODES:
            errors.append(f"{where}: mode must be one of {sorted(MODES)}")
        if (mode == "direct") != ("when" in rule):
            errors.append(f"{where}: 'when' is required for direct services and only for them")
        if mode == "trigger" and "trigger" not in rule:
            errors.append(f"{where}: trigger services need a 'trigger' field")
        if "when" in rule:
            _check_condition(rule["when"], f"{where}.when", errors)
        if "satisfied_when" in rule:
            _check_condition(rule["satisfied_when"], f"{where}.satisfied_when", errors)
        if mode == "prerequisite" and not any(code in s["depends_on"] for s in SERVICES.values()):
            errors.append(f"{where}: prerequisite that no service depends on")

    # Facts ↔ documents, derived conditions
    for doc in FACTS["documents_on_hand"]["values"]:
        if doc not in DOCUMENTS:
            errors.append(f"facts.documents_on_hand: unknown document {doc!r}")
    for key, spec in DERIVED.items():
        if key in FACTS:
            errors.append(f"facts.derived.{key}: clashes with a base fact")
        if "computed" not in spec:
            _check_condition(spec, f"facts.derived.{key}", errors)

    # Questions (bank A) ↔ facts and option mapping
    for gid, g in QUESTION_GROUPS.items():
        if g["bank"] != "A":
            continue
        where = f"questions.{gid}"
        if g["slot"] not in FACTS:
            errors.append(f"{where}: slot {g['slot']!r} is not a fact")
            continue
        _check_condition(applies_when_condition(g.get("applies_when")), f"{where}.applies_when", errors)
        if g.get("type") in NO_OPTION_TYPES:
            continue
        mapped = OPTION_VALUES.get(gid)
        if mapped is None:
            errors.append(f"{where}: no option mapping in facts.json")
            continue
        if len(mapped) != len(g["options"]):
            errors.append(f"{where}: {len(g['options'])} options but {len(mapped)} mapped values")
        for i, value in enumerate(mapped):
            if not is_valid_fact_value(g["slot"], value):
                errors.append(f"{where}: option {i} maps to invalid value {value!r}")
    for gid in OPTION_VALUES.keys() - {g for g, q in QUESTION_GROUPS.items() if q["bank"] == "A"}:
        errors.append(f"facts.options: {gid!r} is not a bank A question group")

    return errors


if __name__ == "__main__":
    problems = validate()
    for p in problems:
        print("ERROR", p)
    print(f"{len(SERVICES)} services, {len(RULES)} rules, {len(FACTS)} facts, {len(QUESTION_GROUPS)} question groups")
    print("OK" if not problems else f"{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)
