"""Whitelist middleware: пускает только владельца и указанных tg_id."""
import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

log = logging.getLogger(__name__)


class WhitelistMiddleware(BaseMiddleware):
    def __init__(self, allowed_ids: set[int]):
        self.allowed = allowed_ids
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None and isinstance(event, CallbackQuery):
            user = event.from_user
        if user is None:
            return

        if user.id not in self.allowed:
            log.warning("Denied access: tg_id=%s username=@%s", user.id, user.username)
            try:
                if isinstance(event, Message):
                    await event.answer(
                        "⛔️ Бот личный. Доступ закрыт.\n\n"
                        f"Твой TG ID: <code>{user.id}</code>",
                        parse_mode="HTML",
                    )
                elif isinstance(event, CallbackQuery):
                    await event.answer("⛔️ Нет доступа", show_alert=True)
            except Exception:
                pass
            return

        return await handler(event, data)
