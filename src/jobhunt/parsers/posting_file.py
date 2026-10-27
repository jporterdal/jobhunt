"""The built-in parser: one JSON posting file (`"format": "jobhunt-posting"`, `"version": 1`) per posting."""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, date, datetime
from urllib.parse import urlsplit

from . import CaptureFile, ParsedPosting, Rejected

FORMAT = "jobhunt-posting"
VERSION = 1
SOURCE = re.compile(r"^[a-z0-9][a-z0-9.-]*$")
WORKPLACE_TYPES = ("On-site", "Hybrid", "Remote")
PRECISIONS = ("minute", "hour", "day", "week", "month", "year")
REQUIRED = ("source", "external_id", "url", "title", "company", "description_html")
OPTIONAL_TEXT = ("location", "workplace_type", "employment_type")
FIELDS = {"format", "version", *REQUIRED, *OPTIONAL_TEXT, "posted_on", "posted_precision", "captured_at",
          "details", "volatile_details"}


class Invalid(Exception):
    pass


class PostingFileParser:
    name = "posting-file"
    version = "1"

    def parse(self, file: CaptureFile) -> ParsedPosting | Rejected | None:
        try:
            data = json.loads(file.raw.decode("utf-8"), parse_constant=_no_constant)
        except (UnicodeDecodeError, ValueError):
            return None
        if not isinstance(data, dict) or data.get("format") != FORMAT:
            return None
        try:
            return _posting(data)
        except Invalid as error:
            return Rejected(str(error))

    def companions(self, path):
        return []


def _no_constant(name: str):
    raise ValueError(f"{name} is not allowed")


def _posting(data: dict) -> ParsedPosting:
    version = data.get("version")
    if type(version) is not int:
        raise Invalid("'version' must be a whole number")
    if version != VERSION:
        raise Invalid(f"unsupported version {version}: this parser reads version {VERSION}")
    unknown = sorted(set(data) - FIELDS)
    if unknown:
        raise Invalid("unknown field " + ", ".join(repr(k) for k in unknown))

    values = {}
    for key in REQUIRED:
        value = data.get(key)
        if value is None:
            raise Invalid(f"missing field {key!r}")
        if not isinstance(value, str):
            raise Invalid(f"{key!r} must be text")
        if not value.strip():
            raise Invalid(f"{key!r} is empty")
        values[key] = value if key == "description_html" else value.strip()
    if not SOURCE.fullmatch(values["source"]):
        raise Invalid("'source' must be lowercase letters, digits, dots and hyphens")
    if urlsplit(values["url"]).scheme.lower() not in ("http", "https"):
        raise Invalid("'url' must be an http or https address")

    for key in OPTIONAL_TEXT:
        value = data.get(key)
        if value is not None and not isinstance(value, str):
            raise Invalid(f"{key!r} must be text")
        values[key] = (value.strip() or None) if value is not None else None
    if values["workplace_type"] is not None and values["workplace_type"] not in WORKPLACE_TYPES:
        raise Invalid(f"'workplace_type' must be one of {', '.join(WORKPLACE_TYPES)}")

    posted_on, precision = _posted(data.get("posted_on"), data.get("posted_precision"))
    return ParsedPosting(
        **values,
        posted_on=posted_on,
        posted_precision=precision,
        captured_at=_captured_at(data.get("captured_at")),
        details=_details("details", data.get("details")),
        volatile_details=_details("volatile_details", data.get("volatile_details")),
    )


def _posted(value, precision) -> tuple[date | None, str | None]:
    if value is None:
        if precision is not None:
            raise Invalid("'posted_precision' is given without 'posted_on'")
        return None, None
    if not isinstance(value, str):
        raise Invalid("'posted_on' must be an ISO date")
    try:
        posted_on = date.fromisoformat(value)
    except ValueError:
        raise Invalid("'posted_on' must be an ISO date") from None
    if precision is None:
        return posted_on, "day"
    if precision not in PRECISIONS:
        raise Invalid(f"'posted_precision' must be one of {', '.join(PRECISIONS)}")
    return posted_on, precision


def _captured_at(value) -> datetime | None:
    if value is None:
        return None
    try:
        moment = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        moment = None
    if moment is None or moment.tzinfo is None:
        raise Invalid("'captured_at' must be an ISO date-time with a time zone")
    return moment.astimezone(UTC)


def _details(key: str, value) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise Invalid(f"{key!r} must be an object")
    for name, item in value.items():
        ok = (
            item is None
            or isinstance(item, (str, bool))
            or (isinstance(item, (int, float)) and math.isfinite(item))
            or (isinstance(item, list) and all(isinstance(i, str) for i in item))
        )
        if not ok:
            raise Invalid(f"{key!r}: {name!r} must be text, a number, true or false, a list of text, or null")
    return dict(value)


PARSER = PostingFileParser()
