"""Forgiving parsers for free-text bot input.

Each parser returns ``(value, error)`` — exactly one of the two is non-None.
This shape lets the conversation handlers re-ask cleanly instead of crashing.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Optional
from zoneinfo import ZoneInfo

from dateutil import parser as du_parser

# ---------- dates ---------------------------------------------------------

_WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}


def _replace_weekday_words(text: str, today: dt.date) -> str:
    """Replace 'today', 'tomorrow', '<weekday>' at the start of the string
    with a concrete YYYY-MM-DD so dateutil only has to handle the time part."""
    parts = text.strip().split(maxsplit=1)
    if not parts:
        return text
    first = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    if first == "today":
        return f"{today.isoformat()} {rest}".strip()
    if first == "tomorrow":
        return f"{(today + dt.timedelta(days=1)).isoformat()} {rest}".strip()
    if first in _WEEKDAYS:
        target = _WEEKDAYS[first]
        days_ahead = (target - today.weekday()) % 7
        if days_ahead == 0:
            # "friday" said on a Friday means *next* Friday — less surprising
            # for a plans bot than "in zero days".
            days_ahead = 7
        d = today + dt.timedelta(days=days_ahead)
        return f"{d.isoformat()} {rest}".strip()
    return text


def parse_when(text: str, tz_name: str) -> tuple[Optional[dt.datetime], Optional[str]]:
    """Parse a datetime in the user's TZ and return an aware UTC datetime."""
    tz = ZoneInfo(tz_name)
    today_local = dt.datetime.now(tz).date()
    pre = _replace_weekday_words(text, today_local)
    try:
        naive = du_parser.parse(pre, dayfirst=False, fuzzy=False)
    except (ValueError, OverflowError):
        return None, (
            "I couldn't read that as a date/time. Try `2026-07-04 19:30`, "
            "`tomorrow 8pm`, or `friday 19:00`."
        )
    if naive.tzinfo is None:
        naive = naive.replace(tzinfo=tz)
    return naive.astimezone(dt.timezone.utc), None


def parse_day(text: str, tz_name: str) -> tuple[Optional[dt.date], Optional[str]]:
    """Parse just a day (no time). Used by /day."""
    tz = ZoneInfo(tz_name)
    today_local = dt.datetime.now(tz).date()
    pre = _replace_weekday_words(text, today_local)
    try:
        parsed = du_parser.parse(pre, dayfirst=False, fuzzy=False, default=dt.datetime(
            today_local.year, today_local.month, today_local.day,
        ))
    except (ValueError, OverflowError):
        return None, (
            "I couldn't read that as a day. Try `today`, `tomorrow`, "
            "`friday`, or `YYYY-MM-DD`."
        )
    return parsed.date(), None


# ---------- duration -------------------------------------------------------

_DUR_RE = re.compile(
    r"""^\s*
        (?:(?P<h>\d+)\s*h(?:ours?)?)?\s*
        (?:(?P<m>\d+)\s*(?:m(?:in(?:utes?)?)?)?)?
        \s*$""",
    re.X | re.I,
)


def parse_duration(text: str) -> tuple[Optional[int], Optional[str]]:
    """Return minutes. Accepts `90`, `1h`, `1h30`, `1h 30m`, `45m`."""
    s = text.strip()
    if not s:
        return None, "Empty duration."

    # Bare integer = minutes.
    if s.isdigit():
        return int(s), None

    m = _DUR_RE.match(s)
    if not m or (not m.group("h") and not m.group("m")):
        return None, "Try `90`, `1h30`, `2h`, or `45m`."
    hours = int(m.group("h") or 0)
    mins = int(m.group("m") or 0)
    total = hours * 60 + mins
    if total <= 0:
        return None, "Duration must be greater than zero."
    return total, None


# ---------- money ----------------------------------------------------------

_CURRENCY_SYMBOLS = {"€": "EUR", "$": "USD", "£": "GBP"}


def parse_money(text: str) -> tuple[Optional[tuple[int, str]], Optional[str]]:
    """Return ``((cents, currency), None)`` or ``((None, error))``.

    Accepts `12`, `12.50`, `12,50`, `12.50€`, `$12.50`, `free`, `gratis`.
    Default currency is EUR when no symbol is present.
    """
    s = text.strip().lower()
    if s in {"free", "gratis", "0", "0€", "$0"}:
        return (0, "EUR"), None

    currency = "EUR"
    for sym, code in _CURRENCY_SYMBOLS.items():
        if sym in s:
            currency = code
            s = s.replace(sym, "")
            break
    s = s.replace(" ", "").replace(",", ".")
    try:
        amount = float(s)
    except ValueError:
        return None, "Try `12`, `12.50`, `12,50€`, or `free`."
    if amount < 0:
        return None, "Price can't be negative."
    return (round(amount * 100), currency), None
