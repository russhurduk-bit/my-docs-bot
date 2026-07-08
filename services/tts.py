"""TTS через edge-tts (бесплатно, русский голос)."""
from pathlib import Path

import edge_tts

VOICE_FEMALE = "ru-RU-SvetlanaNeural"
VOICE_MALE = "ru-RU-DmitryNeural"


async def speak(text: str, out_path: str | Path, voice: str = VOICE_FEMALE) -> Path:
    out_path = Path(out_path)
    # ограничим длину — в голос выводим только короткие ответы
    cut = text[:1500]
    comm = edge_tts.Communicate(cut, voice=voice, rate="+0%")
    await comm.save(str(out_path))
    return out_path
