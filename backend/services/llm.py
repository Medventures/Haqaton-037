"""OpenAI structured-output calls. Without OPENAI_API_KEY every call returns None and callers fall back."""

import logging
import os
from functools import cache

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, ValidationError

log = logging.getLogger("aqylroute.llm")

DEFAULT_MODEL = "gpt-4.1-mini"


def llm_enabled() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


@cache
def _client() -> OpenAI:
    return OpenAI(timeout=30, max_retries=1)


def parse[T: BaseModel](system: str, user: str, schema: type[T]) -> T | None:
    """One structured-output call. Returns None when the AI is off or the call fails."""
    if not llm_enabled():
        return None
    try:
        response = _client().responses.parse(
            model=os.getenv("OPENAI_MODEL") or DEFAULT_MODEL,
            input=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            text_format=schema,
            temperature=0,
        )
    except (OpenAIError, ValidationError):
        log.exception("OpenAI call failed")
        return None
    return response.output_parsed
