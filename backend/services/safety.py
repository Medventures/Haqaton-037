"""Diagnosis filter for AI output (CLAUDE.md: never name or judge a diagnosis).

Applies to text the AI produces, not to the fixed question texts.
"""

import re

_PATTERNS = [
    r"диагноз",
    r"аутизм",
    r"\bрас\b",
    r"расстройств\w* аутистическ",
    r"\bдцп\b",
    r"церебральн\w* паралич",
    r"синдром\w*",
    r"умственн\w* отсталост",
    r"олигофрен",
    r"задержк\w* (психического|речевого|психоречевого) развития",
    r"\bзпр\b",
    r"\bзрр\b",
    r"\bзпрр\b",
    r"эпилепс",
    r"степен[ьи]",
    r"тяжёл|тяжел",
    r"лёгк\w* форм|легк\w* форм",
    r"\bгрупп[аы] инвалидности\b",
    # Kazakh
    r"аутист",
    r"\bасб\b",  # аутистік спектр бұзылысы
    r"\bбцс\b",
    r"церебралд",
    r"ақыл-ой кемістіг",
    r"дамуының тежелу",
    r"дәреже",
    r"ауыр түр",
    r"ауыр дәреже",
    r"мүгедектік тоб",
]
_RE = re.compile("|".join(_PATTERNS), re.IGNORECASE)


class DiagnosisInOutput(ValueError):
    pass


def contains_diagnosis(text: str) -> bool:
    return _RE.search(text) is not None


def assert_no_diagnosis(text: str) -> None:
    match = _RE.search(text)
    if match:
        raise DiagnosisInOutput(f"diagnosis-like wording in AI output: {match.group(0)!r}")
