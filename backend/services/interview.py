"""Adaptive interview over questions.json bank A.

Order: five fixed slots, then whichever question decides the most still-undecided services
(weighted by priority), then filler questions until the minimum is reached. The rule engine,
not the AI, decides what applies; the AI only turns free-text answers into fact values.
"""

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel
from sqlmodel import Session, col, select

from models import Case, InterviewAnswer
from schemas import AnswerIn
from services import llm
from services.catalog import (
    FACTS,
    OPTION_VALUES,
    QUESTION_GROUPS,
    RULES,
    SERVICES,
    FactKey,
    dont_know_value,
    is_valid_fact_value,
    option_value,
)
from services.eligibility import (
    Profile,
    build_profile,
    eligible,
    evaluate,
    question_applies,
    referenced_facts,
    service_condition,
    with_prerequisites,
)
from services.safety import contains_diagnosis

MIN_QUESTIONS = 8
MAX_QUESTIONS = 12
DONT_KNOW = "Не знаю"

FIXED_SLOTS = ["age_months", "region", "has_doctor_conclusion", "setting", "documents_on_hand"]
FILLER_SLOTS = ["preferred_channel", "has_curator", "language"]

# Functional scales describe how the child functions: the AI may parse them only when they are the
# question being answered, never pick them up from an answer to another question.
_SCALE_FACTS = {k for k, spec in FACTS.items() if spec["type"] == "scale"}

Kind = Literal["choice", "multi", "age", "months", "text"]
_KINDS: dict[str | None, Kind] = {None: "choice", "multi": "multi", "age": "age", "months": "months", "text": "text"}

_GROUPS_BY_SLOT: dict[str, list[dict[str, Any]]] = defaultdict(list)
for _g in QUESTION_GROUPS.values():
    if _g["bank"] == "A":
        _GROUPS_BY_SLOT[_g["slot"]].append(_g)
_SLOT_ORDER = list(_GROUPS_BY_SLOT)


class AnswerError(ValueError):
    pass


class InterviewOver(Exception):
    pass


class StaleQuestion(Exception):
    pass


@dataclass
class Question:
    slot: str
    group_id: str
    text: str
    hint: str
    kind: Kind
    options: list[str]


# ---------------------------------------------------------------------------
# Question selection


def next_question(case_id: int, facts: dict[str, Any], answered_slots: list[str], today: date) -> Question | None:
    """The next question to ask, or None when the interview is over."""
    if len(answered_slots) >= MAX_QUESTIONS:
        return None
    profile = build_profile(facts, today)
    covered = set(answered_slots) | {k for k, v in facts.items() if v is not None}

    for slot in FIXED_SLOTS:
        if slot not in covered and (group := _pick_group(slot, profile, strict=False)):
            return _question(case_id, group)

    scores = slot_scores(profile)
    candidates = [s for s in _SLOT_ORDER if s not in covered and scores.get(s, 0) > 0]
    candidates = [s for s in candidates if _pick_group(s, profile, strict=True)]
    if candidates:
        best = max(candidates, key=lambda s: scores[s])  # ties keep bank order
        return _question(case_id, _pick_group(best, profile, strict=True))

    if len(answered_slots) >= MIN_QUESTIONS:
        return None
    for slot in FILLER_SLOTS + _SLOT_ORDER:
        if slot not in covered and (group := _pick_group(slot, profile, strict=True)):
            return _question(case_id, group)
    return None


def slot_scores(profile: Profile) -> dict[str, int]:
    """For each unknown fact: how much deciding it matters, summed over undecided services by priority."""
    scores: dict[str, int] = defaultdict(int)

    def add(cond: dict[str, Any] | None, service_code: str) -> None:
        weight = 4 - SERVICES[service_code]["priority_default"]  # priority 1 → 3, 3 → 1
        for fact in referenced_facts(cond):
            if profile.get(fact) is None:
                scores[fact] += weight

    decisions = {code: eligible(code, profile) for code, r in RULES.items() if r["mode"] == "direct"}
    for code, decision in decisions.items():
        if decision is None:
            add(service_condition(code), code)

    # Prerequisites whose "already done" check is still open (e.g. months since the doctor's conclusion).
    open_or_chosen = [code for code, d in decisions.items() if d is not False]
    for code in with_prerequisites(open_or_chosen, profile):
        satisfied = RULES[code].get("satisfied_when")
        if RULES[code]["mode"] == "prerequisite" and satisfied and evaluate(satisfied, profile) is None:
            add(satisfied, code)
    return dict(scores)


def _pick_group(slot: str, profile: Profile, *, strict: bool) -> dict[str, Any] | None:
    """The group for this slot that applies. Non-strict falls back to an undecided one (e.g. age unknown)."""
    groups = _GROUPS_BY_SLOT.get(slot, [])
    decisions = [(g, question_applies(g["group_id"], profile)) for g in groups]
    for g, applies in decisions:
        if applies is True:
            return g
    if not strict:
        for g, applies in decisions:
            if applies is None:
                return g
    return None


def _question(case_id: int, group: dict[str, Any]) -> Question:
    return Question(
        slot=group["slot"],
        group_id=group["group_id"],
        text=variant_text(case_id, group),
        hint=group.get("hint", ""),
        kind=_KINDS[group.get("type")],
        options=list(group.get("options", [])),
    )


def variant_text(case_id: int, group: dict[str, Any]) -> str:
    """Deterministic per case and slot (questions.json `selection`): a returning parent sees the same text."""
    variants = group["variants"]
    digest = hashlib.sha256(f"{case_id}:{group['slot']}".encode()).hexdigest()
    return variants[int(digest, 16) % len(variants)]


# ---------------------------------------------------------------------------
# Answer parsing


def parse_answer(question: Question, answer: AnswerIn, known: set[str], today: date) -> tuple[dict[str, Any], str]:
    """Turn an answer into {fact: value} plus a readable raw answer.

    `known` are facts already answered; free text may fill other facts only if they aren't known yet.
    """
    slot, group_id = question.slot, question.group_id

    if answer.dont_know:
        return {slot: dont_know_value(slot)}, DONT_KNOW

    if answer.option is not None:
        if question.kind != "choice" or answer.option >= len(question.options):
            raise AnswerError("Такого варианта ответа нет")
        return {slot: option_value(group_id, answer.option)}, question.options[answer.option]

    if answer.options is not None:
        if question.kind != "multi" or not answer.options or any(i >= len(question.options) for i in answer.options):
            raise AnswerError("Такого варианта ответа нет")
        indexes = sorted(set(answer.options))
        values = list(dict.fromkeys(v for i in indexes for v in option_value(group_id, i)))
        return {slot: values}, "; ".join(question.options[i] for i in indexes)

    if answer.value is not None:
        if question.kind not in ("age", "months"):
            raise AnswerError("Для этого вопроса нужен вариант ответа")
        return {slot: _checked(slot, answer.value)}, str(answer.value)

    text = (answer.text or "").strip()
    if not text:
        raise AnswerError("Пустой ответ")
    if _normalize(text) in ("не знаю", "незнаю", "білмеймін"):
        return {slot: dont_know_value(slot)}, text

    match question.kind:
        case "text":
            if contains_diagnosis(text):
                raise AnswerError("Здесь нужен только город или район")
            return {slot: _checked(slot, text)}, text
        case "age":
            months = parse_age_months(text, today)
            if months is not None:
                return {slot: _checked(slot, months)}, text
        case "months":
            months = parse_duration_months(text, default_unit="months")
            if months is not None:
                return {slot: _checked(slot, months)}, text
        case "choice":
            index = _match_option(text, question.options)
            if index is not None:
                return {slot: option_value(group_id, index)}, text

    extracted = extract_facts(question, text, known)
    if not extracted:
        raise AnswerError("Не удалось разобрать ответ. Выберите вариант или ответьте «Не знаю».")
    extracted.setdefault(slot, None)
    return extracted, text


def _checked(fact: str, value: Any) -> Any:
    if not is_valid_fact_value(fact, value):
        raise AnswerError("Значение вне допустимого диапазона")
    return value


def _normalize(text: str) -> str:
    return re.sub(r"[\s.!,]+", " ", text.lower().replace("ё", "е")).strip()


def _match_option(text: str, options: list[str]) -> int | None:
    norm = _normalize(text)
    for i, option in enumerate(options):
        if _normalize(option) == norm:
            return i
    return None


_DATE_RE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")
_YEARS_RE = re.compile(r"(\d+)\s*(?:год|лет|г\b|г\.|жас)")
_MONTHS_RE = re.compile(r"(\d+)\s*(?:мес|м\b|м\.|ай)")


def parse_age_months(text: str, today: date) -> int | None:
    """«3 года 2 месяца», «18 мес», «4», or a birth date «12.05.2022»."""
    if m := _DATE_RE.search(text):
        try:
            born = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
        if born > today:
            return None
        return (today.year - born.year) * 12 + today.month - born.month - (today.day < born.day)
    return parse_duration_months(text, default_unit="years")


def parse_duration_months(text: str, default_unit: Literal["years", "months"]) -> int | None:
    """«полгода», «полтора года», «2 года», «3 месяца», or a bare number in `default_unit`."""
    t = _normalize(text)
    years, months = _YEARS_RE.search(t), _MONTHS_RE.search(t)
    if years or months:
        return (int(years.group(1)) * 12 if years else 0) + (int(months.group(1)) if months else 0)
    if "полтора" in t:
        return 18
    if "полгода" in t or "пол года" in t:
        return 6
    if re.fullmatch(r"(около |примерно )?год( назад)?", t):
        return 12
    if re.fullmatch(r"\d{1,3}", t):
        return int(t) * 12 if default_unit == "years" else int(t)
    return None


# ---------------------------------------------------------------------------
# AI: free text → facts


class ExtractedFact(BaseModel):
    fact: FactKey
    value: bool | int | str | list[str] | None


class Extraction(BaseModel):
    facts: list[ExtractedFact]


_EXTRACT_SYSTEM = """Ты разбираешь ответ родителя в интервью социальной службы Казахстана.
Верни только факты из словаря, которые родитель назвал прямо. Не угадывай и не додумывай.
Значения бери строго из словаря. Если значение неясно — не возвращай этот факт.
Для факта вопроса выбирай самый точный вариант из options_to_values (например, отказ важнее, чем «дома»).
Один ответ может назвать несколько фактов — верни каждый, который назван прямо, а не только факт вопроса.
Никогда не выводи и не записывай диагнозы, степень или тяжесть состояния ребёнка."""


def extract_facts(question: Question, text: str, known: set[str]) -> dict[str, Any]:
    """AI parsing of a free-text answer, limited to catalog fact codes and checked against facts.json."""
    allowed = {question.slot} | {k for k in FACTS if k not in known and k not in _SCALE_FACTS}
    vocabulary = {k: {f: v for f, v in FACTS[k].items() if f != "dont_know"} for k in FACTS if k in allowed}
    options = {}
    if question.options:
        options = dict(zip(question.options, OPTION_VALUES[question.group_id], strict=True))
    prompt = json.dumps(
        {
            "question": question.text,
            "question_fact": question.slot,
            "options_to_values": options,
            "facts_vocabulary": vocabulary,
            "notes": "age_months и months_since_diagnosis — целые числа месяцев. set — список значений.",
            "answer": text,
        },
        ensure_ascii=False,
    )
    result = llm.parse(_EXTRACT_SYSTEM, prompt, Extraction)
    if result is None:
        return {}

    facts: dict[str, Any] = {}
    for item in result.facts:
        fact, value = item.fact.value, item.value
        if fact not in allowed or value is None or not is_valid_fact_value(fact, value):
            continue
        if isinstance(value, str) and contains_diagnosis(value):
            continue
        facts[fact] = sorted(set(value), key=value.index) if isinstance(value, list) else value
    return facts


# ---------------------------------------------------------------------------
# Case-level operations


def answers_for(session: Session, case: Case) -> list[InterviewAnswer]:
    stmt = select(InterviewAnswer).where(InterviewAnswer.case_id == case.id).order_by(col(InterviewAnswer.id))
    return list(session.exec(stmt).all())


def current_question(session: Session, case: Case, today: date) -> tuple[Question | None, int]:
    """The question to show now and how many have been answered."""
    answered = [a.slot for a in answers_for(session, case)]
    if case.status != "interview":
        return None, len(answered)
    return next_question(case.id, case.facts, answered, today), len(answered)


def submit_answer(session: Session, case: Case, answer: AnswerIn, today: date) -> None:
    question, _ = current_question(session, case, today)
    if question is None:
        raise InterviewOver()
    if answer.slot != question.slot:
        raise StaleQuestion()

    answered = {a.slot for a in answers_for(session, case)}
    known = answered | {k for k, v in case.facts.items() if v is not None}
    parsed, raw = parse_answer(question, answer, known, today)

    facts = dict(case.facts)
    facts[question.slot] = parsed[question.slot]
    for fact, value in parsed.items():
        if fact != question.slot and fact not in known:
            facts[fact] = value
    case.facts = facts
    session.add(case)
    session.add(
        InterviewAnswer(
            case_id=case.id,
            slot=question.slot,
            group_id=question.group_id,
            question_text=question.text,
            raw_answer=raw[:1000],
            parsed=parsed,
        )
    )
    session.commit()
    session.refresh(case)

