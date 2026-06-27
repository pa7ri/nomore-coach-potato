"""Entrypoint. Builds the bot Application and either long-polls (local dev,
MODE=poll) or serves an aiohttp webhook on $PORT (Render, MODE=webhook).

In webhook mode we don't use PTB's bundled run_webhook — instead we own the
aiohttp app so we can expose a proper /healthz for Render's health check
and verify Telegram's secret token header on the way in.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal

from aiohttp import web
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, ApplicationBuilder

from app import db
from app.handlers import common as common_handlers
from app.handlers import movies as movies_handlers
from app.handlers import plans as plans_handlers

log = logging.getLogger("ncp")


def register_handlers(app: Application) -> None:
    # Order matters: feature handlers first, common's unknown-command
    # catch-all LAST so it doesn't swallow real commands.
    plans_handlers.register(app)
    movies_handlers.register(app)
    common_handlers.register(app)


async def _post_init(app: Application) -> None:
    app.bot_data["pool"] = await db.init_pool()


async def _post_shutdown(app: Application) -> None:
    pool = app.bot_data.get("pool")
    if pool is not None:
        await db.close_pool(pool)


def _build_app() -> Application:
    token = os.environ["BOT_TOKEN"]
    builder = (
        ApplicationBuilder()
        .token(token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
    )
    app = builder.build()
    register_handlers(app)
    return app


# ---------- webhook mode ---------------------------------------------------

async def _run_webhook(app: Application) -> None:
    """Initialize PTB, set the webhook on Telegram's side, then run an aiohttp
    server until SIGTERM/SIGINT. Updates are pushed into PTB via update_queue.

    Tolerates a missing PUBLIC_URL on boot: serves /healthz so Render's health
    check passes, and skips set_webhook until the env var is filled in. This
    means the very first deploy (before you know the URL) can land healthy.
    """
    public_url = os.environ.get("PUBLIC_URL", "").rstrip("/")
    secret = os.environ["WEBHOOK_SECRET"]
    port = int(os.environ.get("PORT", "8080"))
    url_path = f"/telegram/{secret}"

    async def healthz(_request: web.Request) -> web.Response:
        return web.Response(text="ok")

    async def telegram(request: web.Request) -> web.Response:
        # Verify Telegram's secret header — anyone who somehow learns the URL
        # path can't actually deliver updates without it.
        header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if header_secret != secret:
            return web.Response(status=401, text="bad secret")
        try:
            data = await request.json()
        except Exception:
            return web.Response(status=400, text="bad json")
        update = Update.de_json(data, app.bot)
        await app.update_queue.put(update)
        return web.Response(text="ok")

    aio = web.Application()
    aio.router.add_get("/healthz", healthz)
    aio.router.add_post(url_path, telegram)

    # Bring PTB up.
    await app.initialize()
    if public_url:
        webhook_url = f"{public_url}{url_path}"
        await app.bot.set_webhook(
            url=webhook_url,
            secret_token=secret,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=False,
        )
        log.info("webhook set: %s", webhook_url)
    else:
        log.warning(
            "PUBLIC_URL not set — skipping set_webhook. "
            "/healthz will still respond so the service stays healthy. "
            "Set PUBLIC_URL to your Render URL and redeploy to start receiving updates."
        )
    await app.start()

    runner = web.AppRunner(aio)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    log.info("aiohttp serving on :%s", port)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows / some sandboxes
            pass

    try:
        await stop.wait()
    finally:
        log.info("shutting down")
        await runner.cleanup()
        await app.stop()
        await app.shutdown()


def main() -> None:
    load_dotenv()
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
        level=logging.INFO,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    mode = os.environ.get("MODE", "poll").lower()
    app = _build_app()

    if mode == "webhook":
        asyncio.run(_run_webhook(app))
    else:
        log.info("starting long-polling (MODE=poll)")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
