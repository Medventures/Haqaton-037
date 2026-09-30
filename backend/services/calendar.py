"""iCalendar export of a plan's deadlines, so the family gets reminders in their phone calendar."""

from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

Lang = Literal["ru", "kk"]

_LABELS = {
    "ru": {"prefix": "Срок", "where": "Куда обращаться", "basis": "Основание", "calendar": "AqylRoute — план"},
    "kk": {"prefix": "Мерзім", "where": "Қайда жүгіну керек", "basis": "Негізі", "calendar": "AqylRoute — жоспар"},
}


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> list[str]:
    """RFC 5545: lines longer than 75 octets continue on the next line after a space."""
    parts, current = [], ""
    for char in line:
        if len((current + char).encode("utf-8")) > (75 if not parts else 74):
            parts.append(current)
            current = char
        else:
            current += char
    parts.append(current)
    return [parts[0], *(" " + p for p in parts[1:])]


def _pick(step: dict[str, Any], field: str, lang: Lang) -> str:
    return (step.get(f"{field}_kk") if lang == "kk" else None) or step.get(field) or ""


def plan_calendar(case_id: int, label: str, steps: list[dict[str, Any]], lang: Lang = "ru") -> str:
    """One all-day event per unfinished step on its deadline, with a reminder three days before."""
    words = _LABELS[lang]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//AqylRoute AI//Plan//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(f'{words['calendar']}: {label}')}",
    ]
    for step in steps:
        if step["status"] == "done" or not step.get("due_date"):
            continue
        day = date.fromisoformat(step["due_date"])
        description = "\n".join(
            part
            for part in (
                _pick(step, "parent_explanation", lang),
                f"{words['where']}: {_pick(step, 'responsible', lang)}",
                _pick(step, "deadline_note", lang),
                f"{words['basis']}: {step.get('legal_source', '')}",
            )
            if part
        )
        lines += [
            "BEGIN:VEVENT",
            f"UID:aqylroute-{case_id}-{step['step_id']}@aqylroute",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
            f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{_escape(f'{words['prefix']}: {_pick(step, 'title', lang)}')}",
            f"DESCRIPTION:{_escape(description)}",
            *([f"URL:{step['legal_url']}"] if step.get("legal_url") else []),
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            "TRIGGER:-P3D",
            f"DESCRIPTION:{_escape(_pick(step, 'title', lang))}",
            "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "".join(folded + "\r\n" for line in lines for folded in _fold(line))
