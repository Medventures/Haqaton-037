"""Overdue is computed on read against `today` (the demo passes ?today=), never stored."""

import re
from datetime import date
from typing import Any

from services.catalog import CATALOG_META, SERVICES

LEVEL_2_AFTER_DAYS = 7  # level 1: 1–7 days late, level 2: more than 7

# «10–30 активных случаев на одного социального работника …» → (10, 30)
_norm = re.match(r"(\d+)\D+(\d+)", CATALOG_META["curator_workload_norm"])
LOAD_NORM_MIN, LOAD_NORM_MAX = (int(_norm.group(1)), int(_norm.group(2))) if _norm else (10, 30)


def overdue_days(step: dict[str, Any], today: date) -> int:
    if step["status"] == "done" or not step.get("due_date"):
        return 0
    return max(0, (today - date.fromisoformat(step["due_date"])).days)


def level(days: int) -> int:
    if days <= 0:
        return 0
    return 1 if days <= LEVEL_2_AFTER_DAYS else 2


def with_overdue(steps: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """Copies of the steps with `days_overdue` and `overdue_level` filled in."""
    result = []
    for step in steps:
        days = overdue_days(step, today)
        result.append({**step, "days_overdue": days, "overdue_level": level(days)})
    return result


def summary(steps: list[dict[str, Any]], today: date) -> dict[str, int]:
    levels = [level(overdue_days(s, today)) for s in steps]
    return {
        "steps_total": len(steps),
        "steps_done": sum(s["status"] == "done" for s in steps),
        "overdue_count": sum(lv > 0 for lv in levels),
        "worst_level": max(levels, default=0),
    }


def curator_load(active_cases: int) -> dict[str, Any]:
    state = "below" if active_cases < LOAD_NORM_MIN else "above" if active_cases > LOAD_NORM_MAX else "within"
    return {
        "active_cases": active_cases,
        "norm_min": LOAD_NORM_MIN,
        "norm_max": LOAD_NORM_MAX,
        "state": state,
        "norm_source": CATALOG_META["curator_workload_norm"],
    }


def escalation_message(step: dict[str, Any], case_label: str, today: date) -> dict[str, Any]:
    """A ready-to-send request to the responsible organization about an overdue step."""
    days = overdue_days(step, today)
    due = date.fromisoformat(step["due_date"]).strftime("%d.%m.%Y")
    lines = [
        f"Кому: {step['responsible']}",
        "",
        "Здравствуйте.",
        f"По обращению семьи ({case_label}) по услуге «{step['title']}» срок истёк {due}, "
        f"просрочка {days} дн.",
        f"Основание: {step['legal_source']}.",
        "Просим сообщить, на каком этапе рассмотрение, и назвать дату решения.",
    ]
    warning = SERVICES[step["service_id"]].get("financial_risk")
    if warning:
        lines.append(f"Обращаем внимание: {warning[0].lower()}{warning[1:]}")
    lines += ["", "С уважением, куратор семьи"]
    return {
        "recipient": step["responsible"],
        "days_overdue": days,
        "overdue_level": level(days),
        "warning": warning,
        "message": "\n".join(lines),
    }
