"""Rule engine: decides which catalog services apply. The LLM never does this (CLAUDE.md, core rule 1).

Three-valued (Kleene) logic: True / False / None, where None means "undecided" because a fact
is unknown. «Не знаю» and unanswered questions leave facts unknown.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

from services.catalog import DERIVED, QUESTION_GROUPS, RULES, SERVICES

Tri = bool | None
Condition = dict[str, Any]
Profile = dict[str, Any]

_OPERATORS = ("eq", "ne", "in", "gte", "gt", "lt", "lte", "contains", "contains_any")


def build_profile(facts: dict[str, Any], today: date) -> Profile:
    """Base facts plus derived facts (from facts.json) evaluated for `today`."""
    profile = {k: v for k, v in facts.items() if k not in DERIVED}
    for key, spec in DERIVED.items():
        if spec.get("computed") == "today.month":
            profile[key] = today.month
        else:
            profile[key] = evaluate(spec, profile)
    return profile


def evaluate(cond: Condition, profile: Profile) -> Tri:
    if "all" in cond:
        return _kleene_all([evaluate(c, profile) for c in cond["all"]])
    if "any" in cond:
        return _kleene_any([evaluate(c, profile) for c in cond["any"]])
    if "not" in cond:
        result = evaluate(cond["not"], profile)
        return None if result is None else not result

    value = profile.get(cond["fact"])
    if value is None:
        return None
    op = next(k for k in cond if k in _OPERATORS)
    arg = cond[op]
    match op:
        case "eq":
            return value == arg
        case "ne":
            return value != arg
        case "in":
            return value in arg
        case "gte":
            return value >= arg
        case "gt":
            return value > arg
        case "lt":
            return value < arg
        case "lte":
            return value <= arg
        case "contains":
            return arg in value
        case "contains_any":
            return any(a in value for a in arg)
    raise ValueError(f"unknown operator in {cond}")


def _kleene_all(results: list[Tri]) -> Tri:
    if False in results:
        return False
    return None if None in results else True


def _kleene_any(results: list[Tri]) -> Tri:
    if True in results:
        return True
    return None if None in results else False


def service_condition(service_code: str) -> Condition | None:
    """The full `when` condition of a direct service, including catalog age limits."""
    rule = RULES[service_code]
    if rule["mode"] != "direct":
        return None
    parts = [rule["when"]]
    limits = SERVICES[service_code].get("eligibility", {})
    if "min_age_months" in limits:
        parts.append({"fact": "age_months", "gte": limits["min_age_months"]})
    if "max_age_months" in limits:
        parts.append({"fact": "age_months", "lt": limits["max_age_months"]})
    return {"all": parts}


def eligible(service_code: str, profile: Profile) -> Tri:
    """Does this service apply on its own? Prerequisite and trigger services never do."""
    cond = service_condition(service_code)
    return False if cond is None else evaluate(cond, profile)


@dataclass
class Selection:
    selected: list[str]  # services for the plan, prerequisites included, in dependency order
    undecided: list[str]  # direct services that unknown facts keep open (shown to the curator)


def select_services(profile: Profile) -> Selection:
    decisions = {code: eligible(code, profile) for code, r in RULES.items() if r["mode"] == "direct"}
    chosen = [code for code, d in decisions.items() if d is True]
    undecided = [code for code, d in decisions.items() if d is None]
    return Selection(selected=with_prerequisites(chosen, profile), undecided=undecided)


def with_prerequisites(codes: list[str], profile: Profile) -> list[str]:
    """Add missing `depends_on` steps (recursively) and return all codes in dependency order."""
    result = set(codes)
    stack = list(codes)
    while stack:
        code = stack.pop()
        for dep in SERVICES[code]["depends_on"]:
            if dep not in result and not _prerequisite_done(dep, code, profile):
                result.add(dep)
                stack.append(dep)
    return dependency_order(result)


def _prerequisite_done(dep: str, dependent: str, profile: Profile) -> bool:
    # If `dep` produces a document `dependent` needs, the step is done when that document is on hand.
    needed = set(SERVICES[dep].get("produces") or []) & set(SERVICES[dependent]["documents_required"])
    if needed:
        return needed <= set(profile.get("documents_on_hand") or [])
    satisfied = RULES[dep].get("satisfied_when")
    return satisfied is not None and evaluate(satisfied, profile) is True


def dependency_order(codes: set[str]) -> list[str]:
    """Topological order over depends_on; ties keep catalog order."""
    ordered: list[str] = []
    remaining = [c for c in SERVICES if c in codes]
    while remaining:
        ready = [c for c in remaining if not any(d in codes and d not in ordered for d in SERVICES[c]["depends_on"])]
        if not ready:
            raise ValueError(f"dependency cycle among {remaining}")
        ordered.extend(ready)
        remaining = [c for c in remaining if c not in ready]
    return ordered


def referenced_facts(cond: Condition | None) -> set[str]:
    """Base facts a condition depends on (derived facts expanded, computed ones dropped)."""
    if cond is None:
        return set()
    if "all" in cond or "any" in cond:
        return set().union(*(referenced_facts(c) for c in cond.get("all", cond.get("any"))))
    if "not" in cond:
        return referenced_facts(cond["not"])
    fact = cond["fact"]
    if fact in DERIVED:
        spec = DERIVED[fact]
        return set() if "computed" in spec else referenced_facts(spec)
    return {fact}


def applies_when_condition(applies_when: dict[str, Any] | None) -> Condition:
    """Convert a questions.json `applies_when` ({fact: spec}) into a rule condition."""
    parts: list[Condition] = []
    for fact, spec in (applies_when or {}).items():
        if isinstance(spec, dict):
            parts.extend({"fact": fact, op: arg} for op, arg in spec.items())
        elif isinstance(spec, list):
            parts.append({"fact": fact, "in": spec})
        else:
            parts.append({"fact": fact, "eq": spec})
    return {"all": parts}


def question_applies(group_id: str, profile: Profile) -> Tri:
    return evaluate(applies_when_condition(QUESTION_GROUPS[group_id].get("applies_when")), profile)
