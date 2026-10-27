"""Salary extractors: find the lines that mention pay and read salary ranges from them."""

from __future__ import annotations

import re

from .pipeline import LLM, SALARY_BASES, SALARY_PERIODS, SalaryItem, conform
from .segment import lines

PAY_LINE = re.compile(
    r"[$€£¥₹]"
    r"|\b(?:USD|CAD|EUR|GBP|AUD|NZD|CHF|INR|JPY|SGD)\b"
    r"|\b\d+(?:\.\d+)?\s?[kK]\b"
    r"|\b(?:salary|salaries|compensation|wages?|pay range|base pay|per hour|hourly|per annum|per year|annually)\b"
    r"|/\s?(?:hr|hour|yr|year|annum)\b",
    re.IGNORECASE,
)

RANGES_SCHEMA = {
    "type": "object",
    "properties": {
        "ranges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "min": {"type": ["number", "null"]},
                    "max": {"type": ["number", "null"]},
                    "currency": {"type": "string"},
                    "period": {"type": "string", "enum": list(SALARY_PERIODS)},
                    "location": {"type": ["string", "null"]},
                    "basis": {"type": "string", "enum": list(SALARY_BASES)},
                    "quote": {"type": "string"},
                },
                "required": ["min", "max", "currency", "period", "location", "basis", "quote"],
            },
        }
    },
    "required": ["ranges"],
}

RANGES_SYSTEM = """You read pay from lines of a job posting.
List every salary or pay range the lines state, one entry per range. A line may state several ranges, for
example one per location or currency.
- "min" and "max": the amounts as plain numbers (175000, not "175k"); use null when one is not given.
- "currency": the ISO code, such as "USD" or "CAD"; use "" when it cannot be told.
- "period": what the amount is paid per.
- "location": the place the range applies to when the text ties it to one, otherwise null.
- "basis": "base" for base salary, "ote" for on-target earnings including commission or bonus, "unclear" otherwise.
- "quote": the shortest exact text containing the range, copied character for character.
Leave out amounts that are not pay (bonuses, budgets, company revenue). If no line states pay, answer {"ranges": []}."""


def pay_lines(text: str) -> list[tuple[int, int]]:
    return [(s, e) for s, e in lines(text) if PAY_LINE.search(text[s:e])]


class PayLineExtractor:
    """Only lines mentioning money or pay go to the model; with none, there is no call."""

    name = "paylines"
    version = 1

    def extract(self, text: str, llm: LLM) -> list[SalaryItem]:
        spans = pay_lines(text)
        if not spans:
            return []
        user = "\n".join(text[s:e] for s, e in spans)
        response = conform("salary", llm.chat_json(RANGES_SYSTEM, user, RANGES_SCHEMA), RANGES_SCHEMA)
        return [
            SalaryItem(
                min=_amount(r["min"]),
                max=_amount(r["max"]),
                currency=r["currency"].strip().upper(),
                period=r["period"],
                location=(r["location"] or "").strip() or None,
                basis=r["basis"],
                quote=r["quote"].strip(),
            )
            for r in response["ranges"]
        ]


def _amount(value: float | None) -> float | None:
    return None if value is None else float(value)


EXTRACTORS = (PayLineExtractor(),)
