"""Plans handlers.

`/addplan` is a ConversationHandler. Each step:
  - accepts the user's text
  - parses it
  - on parse failure, sends a friendly hint and stays in the same state
  - on success, stores the value in ``ctx.user_data`` and moves to the next state

Optional fields (description, duration, price, location, link) accept the
literal word ``skip`` to leave them NULL.

The other commands are stateless and just hit the DB.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app import db
from app.auth import require_allowed
from app.parsers import parse_day, parse_duration, parse_money, parse_when

log = logging.getLogger(__name__)

# Conversation states
TITLE, WHEN, DURATION, PRICE, LOCATION, DESCRIPTION, LINK = range(7)

# Pagination
PAGE_SIZE = 10


def _tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("TIMEZONE", "Europe/Madrid"))


def _format_plan(p: db.Plan, tz: ZoneInfo) -> str:
    local = p.starts_at.astimezone(tz)
    lines = [f"<b>#{p.id} · {p.title}</b>", f"🗓 {local.strftime('%a %d %b %Y, %H:%M')}"]
    if p.duration_min is not None:
        h, m = divmod(p.duration_min, 60)
        if h and m:
            lines.append(f"⏱ {h}h{m}m")
        elif h:
            lines.append(f"⏱ {h}h")
        else:
            lines.append(f"⏱ {m}m")
    if p.price_cents is not None:
        if p.price_cents == 0:
            lines.append("💶 free")
        else:
            lines.append(f"💶 {p.price_cents / 100:.2f} {p.currency or 'EUR'}")
    if p.location:
        lines.append(f"📍 {p.location}")
    if p.description:
        lines.append(p.description)
    if p.link:
        lines.append(f"🔗 {p.link}")
    return "\n".join(lines)


def _skip_or(text: str) -> str | None:
    """`skip` and `-` mean 'leave optional field blank'. Everything else is kept."""
    s = text.strip()
    if s.lower() in {"skip", "-"}:
        return None
    return s


# ---------- /addplan conversation ------------------------------------------

@require_allowed
async def addplan_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["plan"] = {}
    await update.message.reply_text(
        "Let's add a plan. What's the title?\n(Send /cancel any time to abort.)"
    )
    return TITLE


async def addplan_title(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    title = update.message.text.strip()
    if not title:
        await update.message.reply_text("Title can't be empty. Try again:")
        return TITLE
    ctx.user_data["plan"]["title"] = title
    await update.message.reply_text(
        "When? Examples: `2026-07-04 19:30`, `tomorrow 8pm`, `friday 19:00`.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return WHEN


async def addplan_when(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    when, err = parse_when(update.message.text, os.environ.get("TIMEZONE", "Europe/Madrid"))
    if err:
        await update.message.reply_text(err)
        return WHEN
    ctx.user_data["plan"]["starts_at"] = when
    await update.message.reply_text(
        "Duration? Examples: `90`, `1h30`, `2h`, `45m`. Or `skip`."
    )
    return DURATION


async def addplan_duration(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    raw = _skip_or(update.message.text)
    if raw is None:
        ctx.user_data["plan"]["duration_min"] = None
    else:
        mins, err = parse_duration(raw)
        if err:
            await update.message.reply_text(err)
            return DURATION
        ctx.user_data["plan"]["duration_min"] = mins
    await update.message.reply_text(
        "Price? Examples: `12`, `12.50`, `12,50€`, `free`. Or `skip`."
    )
    return PRICE


async def addplan_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    raw = _skip_or(update.message.text)
    if raw is None:
        ctx.user_data["plan"]["price_cents"] = None
        ctx.user_data["plan"]["currency"] = None
    else:
        result, err = parse_money(raw)
        if err:
            await update.message.reply_text(err)
            return PRICE
        cents, currency = result
        ctx.user_data["plan"]["price_cents"] = cents
        ctx.user_data["plan"]["currency"] = currency
    await update.message.reply_text("Location? Or `skip`.")
    return LOCATION


async def addplan_location(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["plan"]["location"] = _skip_or(update.message.text)
    await update.message.reply_text("A short description? Or `skip`.")
    return DESCRIPTION


async def addplan_description(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["plan"]["description"] = _skip_or(update.message.text)
    await update.message.reply_text("A link? Or `skip`.")
    return LINK


async def addplan_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    plan = ctx.user_data["plan"]
    plan["link"] = _skip_or(update.message.text)
    plan["created_by"] = update.effective_user.id

    pool: db.asyncpg.Pool = ctx.application.bot_data["pool"]
    saved = await db.insert_plan(pool, **plan)
    await update.message.reply_html("✅ Added:\n" + _format_plan(saved, _tz()))
    ctx.user_data.pop("plan", None)
    return ConversationHandler.END


async def addplan_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.pop("plan", None)
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# ---------- query commands -------------------------------------------------

@require_allowed
async def cmd_week(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    tz = _tz()
    now_local = dt.datetime.now(tz)
    start = now_local.astimezone(dt.timezone.utc)
    end = (now_local + dt.timedelta(days=7)).astimezone(dt.timezone.utc)
    pool = ctx.application.bot_data["pool"]
    plans = await db.list_plans_between(pool, start, end)
    if not plans:
        await update.message.reply_text("No plans in the next 7 days. 🌱")
        return
    # Group by local date for readability.
    by_day: dict[dt.date, list[db.Plan]] = {}
    for p in plans:
        d = p.starts_at.astimezone(tz).date()
        by_day.setdefault(d, []).append(p)
    chunks = []
    for d in sorted(by_day):
        chunks.append(f"<b>{d.strftime('%A %d %b')}</b>")
        for p in by_day[d]:
            chunks.append(_format_plan(p, tz))
            chunks.append("")  # spacer
    await update.message.reply_html("\n".join(chunks).rstrip())


@require_allowed
async def cmd_day(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    args = ctx.args
    tz_name = os.environ.get("TIMEZONE", "Europe/Madrid")
    if not args:
        await update.message.reply_text(
            "Usage: `/day today`, `/day tomorrow`, `/day friday`, or `/day YYYY-MM-DD`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    day, err = parse_day(" ".join(args), tz_name)
    if err:
        await update.message.reply_text(err)
        return
    tz = ZoneInfo(tz_name)
    start_local = dt.datetime.combine(day, dt.time.min, tzinfo=tz)
    end_local = start_local + dt.timedelta(days=1)
    plans = await db.list_plans_between(
        ctx.application.bot_data["pool"],
        start_local.astimezone(dt.timezone.utc),
        end_local.astimezone(dt.timezone.utc),
    )
    if not plans:
        await update.message.reply_text(f"No plans for {day.strftime('%a %d %b')}. 🌱")
        return
    out = [f"<b>{day.strftime('%A %d %b')}</b>", ""]
    for p in plans:
        out.append(_format_plan(p, tz))
        out.append("")
    await update.message.reply_html("\n".join(out).rstrip())


@require_allowed
async def cmd_randomplan(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    plan = await db.random_upcoming_plan(ctx.application.bot_data["pool"], now)
    if plan is None:
        await update.message.reply_text("No upcoming plans yet. Try /addplan.")
        return
    await update.message.reply_html("🎲 " + _format_plan(plan, _tz()))


def _page_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup | None:
    if total_pages <= 1:
        return None
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("◀ Prev", callback_data=f"plans:{page - 1}"))
    buttons.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="plans:noop"))
    if page < total_pages - 1:
        buttons.append(InlineKeyboardButton("Next ▶", callback_data=f"plans:{page + 1}"))
    return InlineKeyboardMarkup([buttons])


async def _render_plans_page(pool, page: int, tz: ZoneInfo) -> tuple[str, InlineKeyboardMarkup | None]:
    offset = page * PAGE_SIZE
    plans, total = await db.list_plans_page(pool, offset=offset, limit=PAGE_SIZE)
    if total == 0:
        return "No plans yet. Try /addplan.", None
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    lines = [f"<b>All plans ({total})</b>", ""]
    for p in plans:
        lines.append(_format_plan(p, tz))
        lines.append("")
    return "\n".join(lines).rstrip(), _page_keyboard(page, total_pages)


@require_allowed
async def cmd_listplans(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text, kb = await _render_plans_page(ctx.application.bot_data["pool"], 0, _tz())
    await update.message.reply_html(text, reply_markup=kb)


async def cb_plans_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data == "plans:noop":
        return
    try:
        page = int(data.split(":", 1)[1])
    except (ValueError, IndexError):
        return
    text, kb = await _render_plans_page(ctx.application.bot_data["pool"], page, _tz())
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@require_allowed
async def cmd_delplan(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("Usage: `/delplan <id>`", parse_mode=ParseMode.MARKDOWN)
        return
    ok = await db.delete_plan(ctx.application.bot_data["pool"], int(ctx.args[0]))
    await update.message.reply_text("🗑 Deleted." if ok else "Nothing with that id.")


# ---------- registration --------------------------------------------------

def register(app: Application) -> None:
    conv = ConversationHandler(
        entry_points=[CommandHandler("addplan", addplan_start)],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addplan_title)],
            WHEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, addplan_when)],
            DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, addplan_duration)],
            PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addplan_price)],
            LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, addplan_location)],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, addplan_description)],
            LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, addplan_link)],
        },
        fallbacks=[CommandHandler("cancel", addplan_cancel)],
        name="addplan",
        persistent=False,
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("day", cmd_day))
    app.add_handler(CommandHandler("randomplan", cmd_randomplan))
    app.add_handler(CommandHandler("listplans", cmd_listplans))
    app.add_handler(CommandHandler("delplan", cmd_delplan))
    app.add_handler(CallbackQueryHandler(cb_plans_page, pattern=r"^plans:"))
