"""Canonical RoofSpan visit outcomes — the SINGLE source of truth for both Office and Field.

Stored values (DB `visits.outcome`) are the keys; labels are the user-facing strings. Any route that
accepts a visit outcome must validate against this set so arbitrary/unsupported strings are rejected.
"""

# Ordered mapping stored_value -> display label (order is the canonical UI order).
VISIT_OUTCOMES = {
    "no_answer": "No answer",
    "not_interested": "Not interested",
    "interested": "Interested",
    "callback": "Callback requested",
    "appointment": "Appointment set",
    "do_not_knock": "Do Not Knock",
}

VALID_VISIT_OUTCOMES = tuple(VISIT_OUTCOMES.keys())


def is_valid_outcome(value: str) -> bool:
    return value in VISIT_OUTCOMES


def validate_outcome(value: str) -> str:
    """Return the value if it is a canonical outcome, else raise ValueError (→ 422 via Pydantic)."""
    if value not in VISIT_OUTCOMES:
        raise ValueError(
            f"Invalid visit outcome '{value}'. Allowed: {', '.join(VALID_VISIT_OUTCOMES)}"
        )
    return value
