"""Movies handlers.

Movies are intentionally lightweight — no ConversationHandler. Add with
``/addmovie Title | optional note | optional link`` and you're done.
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from app import db
from app.auth import require_allowed

log = logging.getLogger(__name__)
PAGE_SIZE = 10


def _format_movie(m: db.Movie) -> str:
    bits = [f"<b>#{m.id} · {m.title}</b>"]
    if m.note:
        bits.append(f"📝 {m.note}")
    if m.link:
        bits.append(f"🔗 {m.link}")
    return "\n".join(bits)


@require_allowed
async def cmd_addmovie(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    raw = update.message.text.split(maxsplit=1)
    if len(raw) < 2 or not raw[1].strip():
        await update.message.reply_text(
            "Usage: `/addmovie Title | optional note | optional link`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    parts = [p.strip() for p in raw[1].split("|")]
    title = parts[0]
    note = parts[1] if len(parts) > 1 and parts[1] else None
    link = parts[2] if len(parts) > 2 and parts[2] else None
    if not title:
        await update.message.reply_text("Title can't be empty.")
        return
    movie = await db.insert_movie(
        ctx.application.bot_data["pool"],
        title=title,
        note=note,
        link=link,
        added_by=update.effective_user.id,
    )
    await update.message.reply_html("🎬 Added:\n" + _format_movie(movie))


def _page_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup | None:
    if total_pages <= 1:
        return None
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("◀ Prev", callback_data=f"movies:{page - 1}"))
    buttons.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="movies:noop"))
    if page < total_pages - 1:
        buttons.append(InlineKeyboardButton("Next ▶", callback_data=f"movies:{page + 1}"))
    return InlineKeyboardMarkup([buttons])


async def _render_movies_page(pool, page: int) -> tuple[str, InlineKeyboardMarkup | None]:
    offset = page * PAGE_SIZE
    movies, total = await db.list_unwatched_page(pool, offset=offset, limit=PAGE_SIZE)
    if total == 0:
        return "No movies in the watchlist. Try `/addmovie The Matrix`.", None
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    lines = [f"<b>Watchlist ({total})</b>", ""]
    for m in movies:
        lines.append(_format_movie(m))
        lines.append("")
    return "\n".join(lines).rstrip(), _page_keyboard(page, total_pages)


@require_allowed
async def cmd_movies(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text, kb = await _render_movies_page(ctx.application.bot_data["pool"], 0)
    await update.message.reply_html(text, reply_markup=kb)


async def cb_movies_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data == "movies:noop":
        return
    try:
        page = int(data.split(":", 1)[1])
    except (ValueError, IndexError):
        return
    text, kb = await _render_movies_page(ctx.application.bot_data["pool"], page)
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@require_allowed
async def cmd_randommovie(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    movie = await db.random_unwatched_movie(ctx.application.bot_data["pool"])
    if movie is None:
        await update.message.reply_text("Watchlist is empty. Try `/addmovie ...`.",
                                        parse_mode=ParseMode.MARKDOWN)
        return
    await update.message.reply_html("🎲🎬 " + _format_movie(movie))


@require_allowed
async def cmd_watched(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("Usage: `/watched <id>`", parse_mode=ParseMode.MARKDOWN)
        return
    ok = await db.mark_watched(ctx.application.bot_data["pool"], int(ctx.args[0]))
    await update.message.reply_text(
        "✅ Marked watched." if ok else "Nothing unwatched with that id."
    )


@require_allowed
async def cmd_delmovie(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("Usage: `/delmovie <id>`", parse_mode=ParseMode.MARKDOWN)
        return
    ok = await db.delete_movie(ctx.application.bot_data["pool"], int(ctx.args[0]))
    await update.message.reply_text("🗑 Deleted." if ok else "Nothing with that id.")


def register(app: Application) -> None:
    app.add_handler(CommandHandler("addmovie", cmd_addmovie))
    app.add_handler(CommandHandler("movies", cmd_movies))
    app.add_handler(CommandHandler("randommovie", cmd_randommovie))
    app.add_handler(CommandHandler("watched", cmd_watched))
    app.add_handler(CommandHandler("delmovie", cmd_delmovie))
    app.add_handler(CallbackQueryHandler(cb_movies_page, pattern=r"^movies:"))
