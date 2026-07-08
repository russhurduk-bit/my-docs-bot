from pathlib import Path

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from config import owner_id
from db import list_history

router = Router()


@router.message(Command("history"))
@router.message(F.text == "🗂 Мои документы")
async def cmd_history(message: Message):
    items = await list_history(owner_id(message.from_user.id), limit=15)
    if not items:
        await message.answer("Пока ничего не сгенерировано. Опиши что нужно — сделаю.")
        return
    lines = ["<b>Последние документы:</b>\n"]
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. <b>{it['title']}</b>\n   <i>{it['created_at']}</i>  /doc_{it['id']}")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(F.text.regexp(r"^/doc_(\d+)$"))
async def cmd_get_doc(message: Message):
    doc_id = int(message.text.split("_")[1])
    items = await list_history(owner_id(message.from_user.id), limit=100)
    item = next((x for x in items if x["id"] == doc_id), None)
    if not item:
        await message.answer("Документ не найден.")
        return
    p = Path(item["pdf_path"])
    if not p.exists():
        await message.answer("Файл не найден на диске.")
        return
    await message.answer_document(FSInputFile(p), caption=item["title"])
