"""STT через faster-whisper. Русский, локально, бесплатно."""
import asyncio
import logging
import subprocess
from pathlib import Path

from faster_whisper import WhisperModel

log = logging.getLogger(__name__)

# small — компромисс скорость/качество для русского; при плохом качестве → medium
_MODEL_SIZE = "small"
_model: WhisperModel | None = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        log.info("Loading faster-whisper model: %s", _MODEL_SIZE)
        _model = WhisperModel(_MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


def _transcribe_sync(audio_path: str) -> str:
    segments, _info = _get_model().transcribe(
        audio_path,
        language="ru",
        vad_filter=True,
        beam_size=1,
    )
    return " ".join(s.text.strip() for s in segments).strip()


async def transcribe_file(input_path: str | Path) -> str:
    """Принимает любой аудио-файл (ogg/opus/mp3/wav), возвращает текст."""
    input_path = str(input_path)
    # faster-whisper сам умеет большинство форматов, но на всякий — конвертим в wav 16k моно
    wav_path = input_path + ".wav"
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-i", input_path,
        "-ar", "16000", "-ac", "1", "-f", "wav", wav_path,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    await proc.wait()
    path_to_use = wav_path if Path(wav_path).exists() else input_path

    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(None, _transcribe_sync, path_to_use)
    try:
        Path(wav_path).unlink(missing_ok=True)
    except Exception:
        pass
    return text
