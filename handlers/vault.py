"""Приём сканов документов, распознавание, шифрованное хранение."""
import logging
from io import BytesIO
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import owner_id
from db import get_profile, upsert_profile
from services import vault, vision

log = logging.getLogger(__name__)
router = Router()

DOC_TYPE_LABELS = {
    "passport_rf": "🛂 Паспорт РФ",
    "passport_intl": "🌍 Загранпаспорт",
    "snils": "📇 СНИЛС",
    "inn": "📇 ИНН",
    "driver_license": "🚗 Водительское",
    "vehicle_reg": "🚙 СТС/ПТС",
    "birth_certificate": "👶 Свидетельство о рождении",
    "marriage_certificate": "💍 Свидетельство о браке",
    "military_id": "🪖 Военный билет",
    "diploma": "🎓 Диплом/аттестат",
    "medical_policy": "🏥 Полис ОМС",
    "bank_card": "💳 Банковская карта",
    "other": "📎 Прочее",
}


async def _download_photo(bot: Bot, file_id: str) -> tuple[bytes, str]:
    f = await bot.get_file(file_id)
    buf = BytesIO()
    await bot.download_file(f.file_path, buf)
    return buf.getvalue(), (f.file_path or "photo.jpg").split("/")[-1]


FIELD_RU = {
    "full_name": "ФИО",
    "birth_date": "Дата рождения",
    "birth_place": "Место рождения",
    "passport_series": "Серия паспорта",
    "passport_number": "Номер паспорта",
    "passport_issued": "Кем выдан",
    "passport_date": "Дата выдачи",
    "passport_code": "Код подразделения",
    "address_reg": "Адрес регистрации",
    "address_live": "Адрес проживания",
    "inn": "ИНН",
    "snils": "СНИЛС",
    "phone": "Телефон",
    "email": "Email",
    "sex": "Пол",
    "registered_address": "Адрес регистрации",
    "driver_license_series": "Серия в/у",
    "driver_license_number": "Номер в/у",
    "driver_license_date": "Дата выдачи в/у",
    "driver_license_categories": "Категории",
}


async def _process_image(message: Message, bot: Bot, file_id: str, fname: str, mime: str):
    """Обёртка: скачивает файл и зовёт _process_image_raw."""
    f = await bot.get_file(file_id)
    buf = BytesIO()
    await bot.download_file(f.file_path, buf)
    await _process_image_raw(message, buf.getvalue(), fname, mime)


async def _process_image_raw(message: Message, raw: bytes, fname: str, mime: str):
    """Распознаёт, сохраняет в vault, автопроапдейтит профиль.
    Дедупликация: (1) sha256 — байт-идентичный скан пропускаем; (2) по содержимому —
    предупреждаем, но сохраняем."""
    import hashlib
    oid = owner_id(message.from_user.id)

    # 1) byte-level dedup — токены не тратим
    sha = hashlib.sha256(raw).hexdigest()
    existing = await vault.find_by_hash(oid, sha)
    if existing:
        await message.answer(
            f"♻️ Такой скан уже есть в хранилище:\n"
            f"<b>{existing.get('title') or existing.get('original_name') or 'документ'}</b>\n"
            f"ID: <code>{existing['id']}</code>  · загружен {existing['created_at']}\n"
            f"Посмотреть: /getfile_{existing['id']}",
            parse_mode="HTML",
        )
        return

    await message.answer("🔐 Распознаю документ...")
    rec = await vision.recognize(raw, mime_type=mime)
    doc_type = rec.get("doc_type", "other")
    fields = rec.get("fields", {}) or {}
    warnings = rec.get("warnings", []) or []

    title = (rec.get("title") or "").strip() or DOC_TYPE_LABELS.get(doc_type, "📎 Документ")

    # 2) semantic dedup — тот же паспорт/СНИЛС/ИНН, новая фотка
    sem_dup = await vault.find_semantic_duplicate(oid, doc_type, fields)

    vault_id = await vault.store_file(
        tg_id=oid,
        raw_bytes=raw,
        original_name=fname,
        mime_type=mime,
        doc_type=doc_type,
        title=title,
        ocr_data=rec,
        sha256=sha,
    )
    log.info("stored file id=%s title=%r doc_type=%s", vault_id, title, doc_type)

    label = DOC_TYPE_LABELS.get(doc_type, "📎 Документ")
    lines = [
        f"🔐 Сохранено: <b>{title}</b>",
        f"   {label}  · id <code>{vault_id}</code>",
    ]
    if sem_dup:
        lines.append(
            f"\nℹ️ Похоже на уже загруженный документ "
            f"<b>{sem_dup.get('title','')}</b> (id <code>{sem_dup['id']}</code>, {sem_dup['created_at']})."
        )

    if fields:
        lines.append("\n<b>Распознанные данные:</b>")
        for k, v in fields.items():
            if not v:
                continue
            ru = FIELD_RU.get(k, k)
            lines.append(f"• {ru}: <code>{v}</code>")

    # Автопроставление в профиль (без подтверждения)
    patch = vision.profile_patch(rec)
    current = await get_profile(oid) if patch else {}
    actually_updated = {}
    if patch:
        # пишем только если поле пустое или отличается
        for k, v in patch.items():
            if not current.get(k) or str(current.get(k)).strip() != str(v).strip():
                actually_updated[k] = v
        if actually_updated:
            await upsert_profile(oid, actually_updated)
            lines.append("\n✅ <b>Профиль обновлён автоматически:</b>")
            for k, v in actually_updated.items():
                ru = FIELD_RU.get(k, k)
                lines.append(f"• {ru} → <code>{v}</code>")
        else:
            lines.append("\n👌 Профиль уже содержит эти данные.")
    elif doc_type != "other":
        lines.append("\nℹ️ Для этого типа документа автозаполнение профиля не предусмотрено.")

    if warnings:
        lines.append("\n⚠️ " + "; ".join(warnings[:3]))

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(F.photo)
async def handle_photo(message: Message, bot: Bot):
    log.info("handle_photo: tg_id=%s photos=%d", message.from_user.id, len(message.photo or []))
    photo = message.photo[-1]
    await _process_image(
        message, bot,
        file_id=photo.file_id,
        fname=f"photo_{photo.file_unique_id}.jpg",
        mime="image/jpeg",
    )


@router.message(F.video | F.animation | F.video_note)
async def handle_video(message: Message, bot: Bot):
    v = message.video or message.animation or message.video_note
    f = await bot.get_file(v.file_id)
    buf = BytesIO()
    await bot.download_file(f.file_path, buf)
    raw = buf.getvalue()
    mime = getattr(v, "mime_type", None) or "video/mp4"
    file_id = await vault.store_file(
        tg_id=owner_id(message.from_user.id),
        raw_bytes=raw,
        original_name=getattr(v, "file_name", None) or f"video_{v.file_id}.mp4",
        mime_type=mime,
        doc_type="other",
        ocr_data={"note": "видео/анимация"},
    )
    kb = round(len(raw) / 1024)
    await message.answer(f"🎥 Видео сохранено в хранилище. ID: <code>{file_id}</code> ({kb} КБ)", parse_mode="HTML")


def _looks_like_image(raw: bytes, fname: str, mime: str) -> tuple[bool, str]:
    """Возвращает (is_image, normalized_mime). Срабатывает даже если MIME
    октет-стрим (Telegram часто так отправляет "файлом без сжатия")."""
    # magic bytes
    if raw.startswith(b"\xff\xd8\xff"):                    return True, "image/jpeg"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):               return True, "image/png"
    if raw.startswith(b"GIF87a") or raw.startswith(b"GIF89a"): return True, "image/gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":        return True, "image/webp"
    if raw[:4] in (b"II*\x00", b"MM\x00*"):                return True, "image/tiff"
    # HEIC/HEIF (ftyp box)
    if len(raw) > 12 and raw[4:8] == b"ftyp":
        brand = raw[8:12]
        if brand in (b"heic", b"heix", b"heim", b"heis", b"mif1", b"msf1"):
            return True, "image/heic"
    # fallback — по расширению
    ext = fname.lower().rsplit(".", 1)[-1] if "." in fname else ""
    ext_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
               "gif": "image/gif", "webp": "image/webp", "heic": "image/heic",
               "heif": "image/heif", "bmp": "image/bmp", "tif": "image/tiff", "tiff": "image/tiff"}
    if ext in ext_map:
        return True, ext_map[ext]
    # mime хоть какой-то image/*
    if mime and mime.startswith("image/"):
        return True, mime
    return False, mime or "application/octet-stream"


@router.message(F.document)
async def handle_document_file(message: Message, bot: Bot):
    doc = message.document
    mime = doc.mime_type or "application/octet-stream"
    log.info("handle_document_file: name=%s mime=%s size=%s", doc.file_name, mime, doc.file_size)

    f = await bot.get_file(doc.file_id)
    buf = BytesIO()
    await bot.download_file(f.file_path, buf)
    raw = buf.getvalue()

    oid = owner_id(message.from_user.id)
    fname = doc.file_name or "file"

    # детект картинки: magic bytes → расширение → mime
    is_img, real_mime = _looks_like_image(raw, fname, mime)
    if is_img:
        log.info("document recognized as image (mime=%s)", real_mime)
        await _process_image_raw(message, raw, fname, real_mime)
        return

    # иначе — просто сохраняем в vault
    rec: dict = {"doc_type": "other", "fields": {}, "warnings": []}
    if mime == "application/pdf":
        rec["warnings"] = ["PDF: нужен OCR — подключим при необходимости"]
        await message.answer("🔐 PDF принят, сохраняю в хранилище.")
    else:
        rec["warnings"] = [f"Файл типа {mime} — без автораспознавания"]
        await message.answer(f"🔐 Файл ({mime or 'без типа'}) сохранён в хранилище.")

    title = doc.file_name or DOC_TYPE_LABELS.get(rec.get("doc_type", "other"), "📎 Документ")
    file_id = await vault.store_file(
        tg_id=oid,
        raw_bytes=raw,
        original_name=doc.file_name or "file",
        mime_type=mime,
        doc_type=rec.get("doc_type", "other"),
        title=title,
        ocr_data=rec,
    )

    await message.answer(
        f"✅ Сохранено: <b>{title}</b>  (id <code>{file_id}</code>)",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("vault_apply:"))
async def cb_apply(cq: CallbackQuery):
    file_id = int(cq.data.split(":")[1])
    async with __import__("aiosqlite").connect(str(__import__("config").DB_PATH)) as db:
        db.row_factory = __import__("aiosqlite").Row
        cur = await db.execute("SELECT ocr_data FROM vault_files WHERE id = ? AND tg_id = ?",
                               (file_id, owner_id(cq.from_user.id)))
        row = await cur.fetchone()
    if not row:
        await cq.answer("Файл не найден")
        return
    import json
    rec = json.loads(row["ocr_data"] or "{}")
    patch = vision.profile_patch(rec)
    if not patch:
        await cq.answer("Нечего применять")
        return
    await upsert_profile(owner_id(cq.from_user.id), patch)
    await cq.message.edit_text(cq.message.html_text + "\n\n✅ Профиль обновлён.", parse_mode="HTML")
    await cq.answer("Готово")


@router.callback_query(F.data.startswith("vault_skip:"))
async def cb_skip(cq: CallbackQuery):
    await cq.message.edit_reply_markup()
    await cq.answer("Пропущено")


def _render_vault_list(items: list[dict], header: str) -> str:
    lines = [f"🔐 <b>{header}</b>\n"]
    for it in items:
        label = DOC_TYPE_LABELS.get(it.get("doc_type"), "📎")
        size_kb = round((it.get("size_bytes") or 0) / 1024)
        title = it.get("title") or it.get("original_name") or "без названия"
        lines.append(
            f"<code>{it['id']:>3}</code> {label} <b>{title}</b>\n"
            f"     <i>{it.get('created_at','')}</i> · {size_kb} КБ · /getfile_{it['id']}"
        )
    lines.append("\n🔎 Поиск: <code>/find &lt;слово&gt;</code>   Удалить: <code>/delfile_ID</code>")
    return "\n".join(lines)


@router.message(Command("vault"))
async def cmd_vault(message: Message):
    items = await vault.list_files(owner_id(message.from_user.id), limit=30)
    if not items:
        await message.answer("🔐 Хранилище пусто. Пришли фото документа — сохраню и распознаю.")
        return
    await message.answer(_render_vault_list(items, "Моё хранилище"), parse_mode="HTML")


@router.message(Command("find"))
async def cmd_find(message: Message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer(
            "Использование: <code>/find паспорт</code>, <code>/find снилс</code>, "
            "<code>/find Иванов</code>, <code>/find 4518</code>.\n\n"
            "Ищу по названию, типу документа, имени файла и распознанным полям.",
            parse_mode="HTML",
        )
        return
    q = parts[1].strip()
    items = await vault.search_files(owner_id(message.from_user.id), q, limit=20)
    if not items:
        await message.answer(f"Ничего не найдено по запросу «{q}».")
        return
    await message.answer(_render_vault_list(items, f"Найдено по «{q}» ({len(items)})"), parse_mode="HTML")


@router.message(F.text.regexp(r"^/getfile_(\d+)$"))
async def cmd_get_file(message: Message):
    fid = int(message.text.split("_")[1])
    res = await vault.read_file(owner_id(message.from_user.id), fid)
    if not res:
        await message.answer("Не найдено.")
        return
    raw, name, mime = res
    await message.answer_document(BufferedInputFile(raw, filename=name))


@router.message(F.text.regexp(r"^/delfile_(\d+)$"))
async def cmd_del_file(message: Message):
    fid = int(message.text.split("_")[1])
    ok = await vault.delete_file(owner_id(message.from_user.id), fid)
    await message.answer("Удалено." if ok else "Не найдено.")
