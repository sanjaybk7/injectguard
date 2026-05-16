"""Module b: SYSTEM_PROMPT is built dynamically (function call result)."""


def _build() -> str:
    return "dynamically built"


SYSTEM_PROMPT = _build()
