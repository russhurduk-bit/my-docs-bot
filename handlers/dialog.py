"""Главный диалог: классификация → консультация или генерация доков с утверждением."""
import json
import logging
from pathlib import Path
from tempfile import NamedTemporaryFile

import aiosqlite
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import DB_PATH, owner_id
from db import (
    add_history,
    clear_dialog_state,
    get_dialog_state,
    get_profile,
    set_dialog_state,
)
from handlers.profile import ProfileFSM
from services import llm, tts
from services.llm import apply_profile_to_html
from services.pdf import render_html_to_pdf

log = logging.getLogger(__name__)
router = Router()

RESERVED_BTNS = {"📄 Новый документ", "👤 Мой профиль", "🗂 Мои документы", "❓ Помощь"}


async def _save_pending(tg_id: int, docs: list[dict]) -> list[int]:
    """Сохраняет сгенерированные, но ещё не утверждённые документы → вернёт ID-шники."""
    ids = []
    async with aiosqlite.connect(DB_PATH) as db:
        for d in docs:
            cur = await db.execute(
                "INSERT INTO pending_docs (tg_id, title, doc_type, html, law_refs, notes, preview_path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    tg_id,
                    d.get("title", "Документ"),
                    d.get("doc_type", "generic"),
                    d.get("html", ""),
                    json.dumps(d.get("law_refs", []), ensure_ascii=False),
                    d.get("notes", ""),
                    d.get("preview_path", ""),
                ),
            )
            ids.append(cur.lastrowid)
        await db.commit()
    return ids


async def _get_pending(tg_id: int, pid: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM pending_docs WHERE id = ? AND tg_id = ?",
            (pid, tg_id),
        )
        row = await cur.fetchone()
    return dict(row) if row else None


async def _delete_pending(tg_id: int, pid: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM pending_docs WHERE id = ? AND tg_id = ?", (pid, tg_id))
        await db.commit()


def _approval_kb(pid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить (подставить мои данные)", callback_data=f"doc_ok:{pid}")],
        [InlineKeyboardButton(text="✏️ Изменить / уточнить", callback_data=f"doc_edit:{pid}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"doc_cancel:{pid}")],
    ])


async def _send_voice_if_requested(message: Message, state: FSMContext, text: str):
    data = await state.get_data()
    if not data.get("want_voice_reply"):
        return
    await state.update_data(want_voice_reply=False)
    try:
        with NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            out = tmp.name
        await tts.speak(text, out)
        await message.answer_voice(FSInputFile(out))
        Path(out).unlink(missing_ok=True)
    except Exception as e:
        log.warning("tts fail: %s", e)


@router.message(F.text, ~F.text.startswith("/"), ~F.text.in_(RESERVED_BTNS))
async def handle_text(message: Message, state: FSMContext):
    if await state.get_state() == ProfileFSM.editing.state:
        return

    tg_id = owner_id(message.from_user.id)
    text = message.text.strip()
    profile = await get_profile(tg_id)

    missing_core = [k for k in ("full_name", "passport_series", "passport_number") if not profile.get(k)]
    profile_hint = (
        "\n\n⚠️ Заполни профиль для автоподстановки: /edit_profile" if missing_core else ""
    )

    dialog = await get_dialog_state(tg_id)
    is_followup = bool(dialog.get("request"))
    known = dialog.get("known_fields", {})

    if is_followup:
        known.setdefault("clarifications", []).append(text)
        pending_request = dialog["request"]
    else:
        try:
            cls = await llm.classify(text)
        except Exception as e:
            log.exception("classify fail")
            await message.answer(f"Ошибка LLM: {e}")
            return

        intent = cls.get("intent")
        if intent == "smalltalk":
            ans = "Привет! Опиши ситуацию или какой документ нужен." + profile_hint
            await message.answer(ans)
            await _send_voice_if_requested(message, state, ans)
            return
        if intent == "history":
            from handlers.history import cmd_history
            await cmd_history(message)
            return
        if intent == "fill_profile":
            await message.answer("Открой: /edit_profile")
            return
        if intent == "consult":
            await message.answer("Думаю...")
            try:
                ans = await llm.consult(text, profile)
            except Exception as e:
                log.exception("consult fail")
                await message.answer(f"Ошибка LLM: {e}")
                return
            await message.answer(ans[:4000] + profile_hint)
            await set_dialog_state(tg_id, {"request": text, "known_fields": {}, "mode": "consult"})
            await _send_voice_if_requested(message, state, ans[:800])
            return

        pending_request = text

    await message.answer("🧠 Готовлю документы...")
    try:
        result = await llm.generate_document_html(
            user_request=pending_request,
            profile=profile,
            known_fields=known,
        )
    except Exception as e:
        log.exception("generate fail")
        await message.answer(f"Ошибка генерации: {e}")
        return

    if result.get("status") == "need_info":
        questions = result.get("questions", [])
        qtext = "❓ Нужно уточнить:\n\n" + "\n".join(f"• {q}" for q in questions)
        qtext += "\n\n_Ответь одним сообщением. /reset — начать заново._"
        await set_dialog_state(tg_id, {
            "request": pending_request,
            "known_fields": known,
            "mode": "doc",
        })
        await message.answer(qtext, parse_mode="Markdown")
        await _send_voice_if_requested(message, state, "Нужно уточнить несколько деталей.")
        return

    docs = result.get("documents", []) or []
    if not docs:
        await message.answer("Документы не сгенерированы. Переформулируй.")
        return

    # превью: рендерим PDF, сохраняем как pending, даём кнопки
    preview_docs = []
    for d in docs:
        inner = d.get("html", "")
        refs = d.get("law_refs", []) or []
        if refs:
            refs_html = "<div class=\"law-refs\">Нормативная база: " + "; ".join(refs) + "</div>"
            if "</article>" in inner:
                inner = inner.replace("</article>", refs_html + "</article>")
            else:
                inner = inner + refs_html

        pdf_path = render_html_to_pdf(inner, f"{d.get('title','doc')}_preview", tg_id)
        d["html"] = inner
        d["preview_path"] = str(pdf_path)
        preview_docs.append(d)

    ids = await _save_pending(tg_id, preview_docs)

    for d, pid in zip(preview_docs, ids):
        caption = f"📄 <b>{d.get('title','Документ')}</b> — черновик"
        if d.get("notes"):
            caption += f"\n\n📌 {d['notes'][:700]}"
        if d.get("law_refs"):
            caption += "\n\n⚖️ " + "; ".join(d["law_refs"][:6])
        caption += "\n\nПросмотри и выбери действие ниже."
        await message.answer_document(
            FSInputFile(Path(d["preview_path"])),
            caption=caption[:1024],
            parse_mode="HTML",
            reply_markup=_approval_kb(pid),
        )

    await clear_dialog_state(tg_id)
    await _send_voice_if_requested(message, state, f"Черновики готовы, {len(ids)} документа. Проверь и подтверди.")


@router.callback_query(F.data.startswith("doc_ok:"))
async def cb_doc_ok(cq: CallbackQuery):
    pid = int(cq.data.split(":")[1])
    pdoc = await _get_pending(owner_id(cq.from_user.id), pid)
    if not pdoc:
        await cq.answer("Черновик не найден")
        return

    profile = await get_profile(owner_id(cq.from_user.id))

    # LLM подставит данные профиля в существующий HTML (вернёт финальный HTML)
    await cq.answer("Подставляю данные...")
    try:
        final_html = await apply_profile_to_html(pdoc["html"], profile, pdoc["title"])
    except Exception as e:
        log.warning("profile apply failed: %s; using original html", e)
        final_html = pdoc["html"]

    pdf_path = render_html_to_pdf(final_html, pdoc["title"], owner_id(cq.from_user.id))
    hid = await add_history(
        tg_id=owner_id(cq.from_user.id),
        title=pdoc["title"],
        doc_type=pdoc["doc_type"],
        pdf_path=str(pdf_path),
        input_data={"from_pending": pid},
    )
    await _delete_pending(owner_id(cq.from_user.id), pid)

    # удалим preview-файл
    try:
        Path(pdoc["preview_path"]).unlink(missing_ok=True)
    except Exception:
        pass

    caption = f"✅ <b>Готово:</b> {pdoc['title']}\n\nДанные подставлены. Остаётся подпись."
    if pdoc.get("notes"):
        caption += f"\n\n📌 {pdoc['notes'][:500]}"

    await cq.message.edit_reply_markup()
    await cq.message.answer_document(
        FSInputFile(pdf_path),
        caption=caption[:1024],
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("doc_edit:"))
async def cb_doc_edit(cq: CallbackQuery):
    pid = int(cq.data.split(":")[1])
    pdoc = await _get_pending(owner_id(cq.from_user.id), pid)
    if not pdoc:
        await cq.answer("Черновик не найден")
        return
    await set_dialog_state(owner_id(cq.from_user.id), {
        "request": f"Доработай документ «{pdoc['title']}»",
        "known_fields": {"original_html": pdoc["html"]},
        "mode": "doc",
        "editing_pid": pid,
    })
    await cq.message.edit_reply_markup()
    await cq.message.answer(
        f"✏️ Редактирование «{pdoc['title']}».\n\n"
        "Напиши что изменить / добавить / убрать — одним сообщением."
    )
    await cq.answer()


@router.callback_query(F.data.startswith("doc_cancel:"))
async def cb_doc_cancel(cq: CallbackQuery):
    pid = int(cq.data.split(":")[1])
    pdoc = await _get_pending(owner_id(cq.from_user.id), pid)
    if pdoc:
        try:
            Path(pdoc["preview_path"]).unlink(missing_ok=True)
        except Exception:
            pass
        await _delete_pending(owner_id(cq.from_user.id), pid)
    await cq.message.edit_reply_markup()
    await cq.answer("Отменено")


