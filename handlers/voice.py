"""Голосовые: STT → текст → обычный dialog handler; опционально TTS-ответ."""
import logging
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, Message

from services import stt

log = logging.getLogger(__name__)
router = Router()


@router.message(F.voice | F.audio)
async def handle_voice(message: Message, bot: Bot, state: FSMContext):
    await message.answer("🎙 Слушаю...")
    v = message.voice or message.audio
    f = await bot.get_file(v.file_id)
    with NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        buf = BytesIO()
        await bot.download_file(f.file_path, buf)
        tmp.write(buf.getvalue())
        tmp_path = tmp.name

    try:
        text = await stt.transcribe_file(tmp_path)
    except Exception as e:
        log.exception("stt fail")
        await message.answer(f"Не смог распознать голос: {e}")
        return
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass

    if not text:
        await message.answer("Пустой результат распознавания. Попробуй ещё раз чётче.")
        return

    await message.answer(f"📝 Распознал: <i>{text}</i>", parse_mode="HTML")

    # проставляем текст в message и передаём в обычный dialog-флоу
    from handlers.dialog import handle_text
    # небольшой хак: подменяем message.text в копии события
    message.text = text  # type: ignore[assignment]
    # помечаем что ответ стоит озвучить
    await state.update_data(want_voice_reply=True)
    await handle_text(message, state)
