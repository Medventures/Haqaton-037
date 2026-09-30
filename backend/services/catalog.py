"""Read-only catalog: services, documents, legal sources, facts, rules, questions.

Loaded once at import. Runtime never regenerates it (CLAUDE.md, core rule 5).
"""

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load(name: str) -> dict[str, Any]:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


_services_raw = _load("services.json")
_facts_raw = _load("facts.json")
_rules_raw = _load("rules.json")
_questions_raw = _load("questions.json")

CATALOG_META: dict[str, Any] = _services_raw["_meta"]
SERVICES: dict[str, dict[str, Any]] = {s["service_code"]: s for s in _services_raw["services"]}
DOCUMENTS: dict[str, dict[str, Any]] = {d["doc_code"]: d for d in _services_raw["documents"]}
LEGAL_SOURCES: dict[str, dict[str, Any]] = {x["id"]: x for x in CATALOG_META["legal_sources"]}

FACTS: dict[str, dict[str, Any]] = _facts_raw["facts"]
DERIVED: dict[str, dict[str, Any]] = _facts_raw["derived"]
OPTION_VALUES: dict[str, list[Any]] = _facts_raw["options"]

RULES: dict[str, dict[str, Any]] = _rules_raw["services"]

QUESTION_GROUPS: dict[str, dict[str, Any]] = {g["group_id"]: g for g in _questions_raw["groups"]}
QUESTIONS_META: dict[str, Any] = _questions_raw["_meta"]

# Enums built from the catalog, so LLM structured outputs cannot return IDs outside it (core rule 4).
ServiceId = StrEnum("ServiceId", [(code, code) for code in SERVICES])
FactKey = StrEnum("FactKey", [(key, key) for key in FACTS])
SlotId = StrEnum(
    "SlotId",
    [(s, s) for s in dict.fromkeys(g["slot"] for g in QUESTION_GROUPS.values() if g["bank"] == "A")],
)


def option_value(group_id: str, index: int) -> Any:
    """Fact value for option `index` of a question group (a list for multi-choice groups)."""
    return OPTION_VALUES[group_id][index]


def dont_know_value(fact: str) -> Any:
    """Value stored when the parent answers «Не знаю» (None unless the fact defines one)."""
    return FACTS[fact].get("dont_know")


def is_valid_fact_value(fact: str, value: Any) -> bool:
    """Check a value against the fact vocabulary. None (unknown) is always valid."""
    if value is None:
        return True
    spec = FACTS.get(fact)
    if spec is None:
        return False
    match spec["type"]:
        case "bool":
            return isinstance(value, bool)
        case "int" | "scale":
            return (
                isinstance(value, int)
                and not isinstance(value, bool)
                and spec.get("min", value) <= value <= spec.get("max", value)
            )
        case "text":
            return isinstance(value, str) and 0 < len(value.strip()) <= 200
        case "enum":
            return value in spec["values"]
        case "set":
            return isinstance(value, list) and all(v in spec["values"] for v in value)
    return False


def legal_source_text(service_code: str) -> str:
    """Human-readable legal reference for a service, e.g. «Приказ МОН РК … (рег. № 20744), прил. 1»."""
    service = SERVICES[service_code]
    source = LEGAL_SOURCES[service["legal_source"]]
    ref = service.get("legal_ref")
    return f"{source['act']}, {ref}" if ref else source["act"]
