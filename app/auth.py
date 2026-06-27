"""Allow-list gate.

Reads ALLOWED_CHAT_IDS once at import time. Empty set = open mode (useful
during local testing — first message logs the user id so you can fill the
env var). In production, set it and only listed users get a response.
"""
from __future__ import annotations

import functools
import logging
import os
from typing import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

log = logging.getLogger(__name__)


def _load_allowed() -> frozenset[int]:
    raw = os.environ.get("ALLOWED_CHAT_IDS", "").strip()
    if not raw:
        return frozenset()
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            log.warning("ignoring non-integer ALLOWED_CHAT_IDS entry: %r", part)
    return frozenset(ids)


_ALLOWED = _load_allowed()


Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


def require_allowed(handler: Handler) -> Handler:
    """Wrap a handler so non-whitelisted users are silently ignored."""
    @functools.wraps(handler)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if user is None:
            return
        if _ALLOWED and user.id not in _ALLOWED:
            log.info(
                "rejected user_id=%s username=%s (not in ALLOWED_CHAT_IDS)",
                user.id, user.username,
            )
            return
        if not _ALLOWED:
            # Open mode: log every caller so the operator can pick IDs for the
            # whitelist. INFO so it shows up in Render logs without DEBUG noise.
            log.info(
                "open mode: user_id=%s username=%s",
                user.id, user.username,
            )
        await handler(update, ctx)

    return wrapper
