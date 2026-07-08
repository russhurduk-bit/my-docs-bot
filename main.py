"""Мои Документы — Telegram-бот для генерации документов РФ."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import ALLOWED_TG_IDS, BOT_TOKEN
from db import init_db
from handlers import build_router
from middleware import WhitelistMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


async def main():
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is empty — заполни .env")

    await init_db()
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    wl = WhitelistMiddleware(ALLOWED_TG_IDS)
    dp.message.middleware(wl)
    dp.callback_query.middleware(wl)
    dp.include_router(build_router())
    log.info("Whitelist: %s", sorted(ALLOWED_TG_IDS))

    me = await bot.get_me()
    log.info("Starting @%s (id=%s)", me.username, me.id)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
