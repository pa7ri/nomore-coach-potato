"""Common handlers: /start, /help, error handler, unknown-command fallback."""
from __future__ import annotations

import logging
import os

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.auth import require_allowed

log = logging.getLogger(__name__)


HELP_TEXT = (
    "<b>nomore-coach-potato</b> — plans &amp; movies for two.\n\n"
    "<b>Plans</b>\n"
    "/addplan — add a plan step by step\n"
    "/week — plans for the next 7 days\n"
    "/day &lt;today|tomorrow|friday|YYYY-MM-DD&gt; — plans on a specific day\n"
    "/randomplan — random upcoming plan\n"
    "/listplans — full list, paginated\n"
    "/delplan &lt;id&gt; — delete a plan\n\n"
    "<b>Movies</b>\n"
    "/addmovie Title | optional note | optional link\n"
    "/movies — unwatched watchlist\n"
    "/randommovie — random pick\n"
    "/watched &lt;id&gt; — mark watched\n"
    "/delmovie &lt;id&gt; — remove\n\n"
    "Timezone: <code>{tz}</code>"
)


@require_allowed
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(
        "👋 Hey! Use /help to see what I can do."
    )


@require_allowed
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    tz = os.environ.get("TIMEZONE", "Europe/Madrid")
    await update.message.reply_html(HELP_TEXT.format(tz=tz))


@require_allowed
async def unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    # Only fires for messages that didn't match any other handler AND aren't
    # part of an active ConversationHandler step (PTB routes those first).
    await update.message.reply_text("I didn't catch that. Try /help.")


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("handler error", exc_info=ctx.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "Something went wrong on my side. The error has been logged."
            )
        except Exception:  # noqa: BLE001 — best-effort apology
            pass


def register(app: Application) -> None:
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    # Unknown-command catch-all. Must be added LAST in main.py.
    app.add_handler(MessageHandler(filters.COMMAND, unknown))
    app.add_error_handler(on_error)
