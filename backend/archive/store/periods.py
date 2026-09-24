"""The per-field timeline: what each product's fields were, and when.

The owner's rule, verbatim: "we keep storing only if it has changed from the last
record. otherwise we just update the period." So for every product and every
tracked field there is a list of periods `{value, from, to}`, oldest first. A run
that sees the same value moves `to` forward; a run that sees a different value
closes the open period at its own time and opens a new one. Nothing is stored per
run except a boundary — a product whose price never moves has one price period,
however many runs read it.

Both backends answer with that shape. In Postgres it is the `product_periods`
table, `period_to` and all. In the JSON catalogue it lives on each product entry
as `periods: {field: [[value, from], ...]}` with `from` in epoch seconds, and no
`to` at all: a closed period ends where the next one begins, and the open one
ends at the product's `last_seen_run`, which the entry already carries. That is
what keeps it under a tenth of the object — the timestamps and the keys were
most of the bytes. `as_dicts` turns the pairs into the rows readers get.

Times are the run's own time (a run id carries its timestamp), truncated to the
second, and shown as `2026-09-24T10:00:00Z`, so the two backends agree to the
character and a re-serialised object never differs from the one it was read from.
"""

from __future__ import annotations

import hashlib
from bisect import bisect_left
from datetime import datetime, timezone
from typing import Any

from backend.archive.domain.product import WATCHED_FIELDS

# The watched commerce fields, plus what a shopper would notice changing.
# `description_sha1` is a hash: the text is long and only "did it change" matters.
PERIOD_FIELDS = (
    *WATCHED_FIELDS,
    "size_info",
    "color_info",
    "material_info",
    "main_image_url",
    "product_title",
    "currency",
    "description_sha1",
)
NUMERIC_FIELDS = ("price", "full_price")
BOOL_FIELDS = ("in_stock",)
MAX_PERIODS = 50  # per field per product; the oldest go first

_FMT = "%Y-%m-%dT%H:%M:%SZ"


def period_time(run_id: str | None) -> datetime:
    """When a run happened, to the second, in UTC. Now when the id says nothing."""
    if run_id:
        stamp_text = run_id.rsplit("-", 1)[0]
        try:
            when = datetime.fromisoformat(stamp_text.replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            return when.astimezone(timezone.utc).replace(microsecond=0)
        except ValueError:
            pass
    return datetime.now(timezone.utc).replace(microsecond=0)


def epoch(run_id: str | None) -> int:
    """A run's time as whole seconds since the epoch — the JSON form's `from`."""
    return int(period_time(run_id).timestamp())


def stamp(when: datetime | int) -> str:
    if isinstance(when, int):
        when = datetime.fromtimestamp(when, tz=timezone.utc)
    return when.astimezone(timezone.utc).replace(microsecond=0).strftime(_FMT)


def normalise(field: str, value: Any) -> Any:
    """One value per field shape, so a re-serialised equal value never opens a period.

    Blanks (None, "", "None") are None. Numbers are floats to 2 dp; a price that
    cannot be read as a number is a blank. `in_stock` is a bool. Text is stripped.
    The description is its sha1.
    """
    if value is None or value == "" or value == "None":
        return None
    if field in NUMERIC_FIELDS:
        try:
            return round(float(value), 2)
        except (TypeError, ValueError):
            return None
    if field in BOOL_FIELDS:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes")
    text = str(value).strip()
    if not text:
        return None
    if field == "description_sha1":
        # The first 16 hex characters: 64 bits is plenty to say "it changed", and
        # the full digest was the largest single value on every product.
        return hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    return text


def values_of(record: dict) -> dict[str, Any]:
    """The tracked fields of a record, normalised. Absent fields are None."""
    out = {}
    for field in PERIOD_FIELDS:
        source = "description" if field == "description_sha1" else field
        out[field] = normalise(field, record.get(source))
    return out


# --- the JSON form: [value, from] pairs on the product entry -------------------------


def apply(periods: dict[str, list], values: dict[str, Any], at: int) -> list[str]:
    """Bring a product's periods up to `at` with these values. Returns the fields
    whose period changed (a new one opened), for callers that count boundaries.

    Same value as the open period: nothing to write — its end is the product's
    last sighting, which the entry keeps. Different: a new period opens at `at`.
    A field that has never had a value and still has none gets nothing — a blank
    is not a fact worth a period. A period that already opened at this second
    (a second reading in one run, or a replayed observation) takes the value
    rather than opening another, as the table's key would.
    """
    opened = []
    for field, value in values.items():
        held = periods.get(field)
        if not held:
            if value is None:
                continue
            periods[field] = [[value, at]]
            opened.append(field)
            continue
        starts = [p[1] for p in held]
        i = bisect_left(starts, at)
        if i < len(held) and held[i][1] == at:
            held[i][0] = value
            continue
        before = held[i - 1][0] if i else None
        if i and before == value:
            continue
        held.insert(i, [value, at])
        opened.append(field)
        if len(held) > MAX_PERIODS:
            del held[: len(held) - MAX_PERIODS]
    return opened


def as_dicts(periods: dict[str, list] | None, last_seen: int | None) -> dict[str, list[dict]]:
    """The reader's rows: each period ends where the next begins, the open one at
    the product's last sighting (never before its own start)."""
    out: dict[str, list[dict]] = {}
    for field, held in (periods or {}).items():
        if not held:
            continue
        rows = []
        for k, (value, start) in enumerate(held):
            end = held[k + 1][1] if k + 1 < len(held) else max(start, last_seen or start)
            rows.append({"value": value, "from": stamp(start), "to": stamp(end)})
        out[field] = rows
    return out


def describe(title: str, field: str, before: Any, after: Any) -> str:
    """One line for the deck: `Nemo Hoodie: price 180 → 126`."""
    if field == "description_sha1":
        return f"{title}: description changed"
    return f"{title}: {field} {_show(before)} → {_show(after)}"


def _show(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    text = str(value)
    return text if len(text) <= 40 else text[:37] + "…"


# --- the table form: value_text / value_num columns ---------------------------------


def to_columns(field: str, value: Any) -> tuple[str | None, float | None]:
    """A normalised value as the two nullable columns of `product_periods`."""
    if value is None:
        return None, None
    if field in NUMERIC_FIELDS:
        return None, float(value)
    if field in BOOL_FIELDS:
        return ("true" if value else "false"), None
    return str(value), None


def from_columns(field: str, value_text: str | None, value_num: float | None) -> Any:
    if field in NUMERIC_FIELDS:
        return None if value_num is None else round(float(value_num), 2)
    if field in BOOL_FIELDS:
        return None if value_text is None else value_text == "true"
    return value_text
