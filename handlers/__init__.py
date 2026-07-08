from aiogram import Router

from handlers import dialog, history, profile, start, vault, voice


def build_router() -> Router:
    root = Router()
    root.include_router(start.router)
    root.include_router(profile.router)
    root.include_router(history.router)
    root.include_router(vault.router)   # фото/документы
    root.include_router(voice.router)   # голосовые — до текстового catch-all
    root.include_router(dialog.router)  # текстовый catch-all
    return root
