"""Распознавание сканов документов РФ через Claude Vision.

Определяет тип и извлекает поля. Предлагает автозаполнение профиля.
"""
import json
import logging
from typing import Any

from config import VISION_CHAIN
from services import llm_providers

log = logging.getLogger(__name__)

SYSTEM = """Ты — распознаватель российских документов. Получаешь изображение (скан/фото).
Твоя задача — найти ВСЕ читаемые поля и вернуть их в JSON. Не ленись, не пропускай поля если они видны.

Определи ТИП документа:
- passport_rf (ВНУТРЕННИЙ паспорт гражданина РФ, любая страница)
- passport_intl (ЗАГРАНпаспорт РФ)
- snils
- inn (свидетельство ИНН физ.лица или ЕГРИП/ЕГРЮЛ)
- driver_license (водительское удостоверение)
- vehicle_reg (СТС / ПТС)
- birth_certificate
- marriage_certificate
- military_id
- diploma
- medical_policy (ОМС/ДМС)
- bank_card
- other

Извлеки поля. Верни СТРОГО JSON:
{
  "doc_type": "passport_rf",
  "title": "Паспорт РФ — Иванов И.И. (основной разворот)",
  "confidence": 0.95,
  "fields": {
    "full_name": "Иванов Иван Иванович",
    "birth_date": "01.01.1990",
    "birth_place": "ГОР. МОСКВА",
    "sex": "МУЖ.",
    "passport_series": "4510",
    "passport_number": "123456",
    "passport_issued": "ОУФМС России по гор. Москве по району Арбат",
    "passport_date": "15.03.2010",
    "passport_code": "770-001",
    "registered_address": "123456, г. Москва, ул. Ленина, д. 1, кв. 1",
    "snils": "123-456-789 00",
    "inn": "770123456789",
    "driver_license_series": "99 АА",
    "driver_license_number": "123456",
    "driver_license_date": "01.01.2020",
    "driver_license_categories": "B, B1"
  },
  "warnings": []
}

ВАЖНО про title:
- Короткое человеческое название, которое легко найти поиском.
- Включай фамилию если видна. Включай уточнение какая страница/сторона если важно.
- Примеры:
  • "Паспорт РФ — Иванов И.И. (основной разворот)"
  • "Паспорт РФ — Иванов И.И. (прописка)"
  • "СНИЛС — Иванов И.И."
  • "ИНН — Иванов И.И."
  • "Водительское удостоверение — Иванов И.И."
  • "СТС — Toyota Camry А123АА77"
  • "Загранпаспорт — Иванов И.И. (основной разворот)"
- Если документ не опознан — title="Нераспознанный документ".

КАК ОТЛИЧИТЬ внутренний паспорт РФ от загранпаспорта (ТЫ ПОСТОЯННО ПУТАЕШЬ — ЧИТАЙ ВНИМАТЕЛЬНО):

ВНУТРЕННИЙ паспорт РФ (passport_rf):
- Страница с фото: фон СВЕТЛО-РОЗОВЫЙ/бежевый с водяными знаками в виде герба РФ и слов "РОССИЯ".
- Текст ВСЕХ полей — ТОЛЬКО НА РУССКОМ. Никакой латиницы, никакой английской транслитерации рядом с ФИО.
- Заголовки: "Фамилия", "Имя", "Отчество", "Пол", "Дата рождения", "Место рождения" — кириллицей.
- Вверху страницы "Паспорт выдан" и орган выдачи ТОЛЬКО на русском.
- Сверху справа: серия+номер 4+6 цифр (например "45 18  №  123456"), напечатанные красным.
- Машиночитаемая зона внизу (2 строки) НАЧИНАЕТСЯ С "PNRUS" — это верный признак внутреннего паспорта РФ.
- Обложка (если видно) — тёмно-бордовая/красная с золотым гербом РФ, надпись "ПАСПОРТ РОССИЙСКОЙ ФЕДЕРАЦИИ" на русском.
- Страница прописки — синие штампы "Зарегистрирован по месту жительства".

ЗАГРАНПАСПОРТ РФ (passport_intl):
- Страница с фото: биометрическая, серого/сиреневого цвета, ПЛАСТИКОВАЯ.
- Поля ДВУЯЗЫЧНЫЕ: под каждым заголовком идёт пара "Фамилия / Surname", "Имя / Given names" и т.д. ФИО и место рождения продублированы латиницей.
- Вверху "РОССИЙСКАЯ ФЕДЕРАЦИЯ / ROSSIJSKAJA FEDERACIJA" и "ПАСПОРТ / PASSPORT".
- Серия — 2 цифры, номер — 7 цифр.
- МЧЗ внизу НАЧИНАЕТСЯ С "P<RUS" (с угловой скобкой после P).
- Обложка — ТЁМНО-СИНЯЯ (у дипломатических — зелёная) с гербом РФ и надписью "PASSPORT" латиницей.

ПРАВИЛО ПРИНЯТИЯ РЕШЕНИЯ:
- Если ФИО продублировано транслитерацией (есть строка "IVANOV" рядом со строкой "Иванов") → passport_intl.
- Если все надписи только на кириллице → passport_rf.
- MRZ "PNRUS..." → passport_rf, "P<RUS..." → passport_intl.
- Формат серии/номера: 4+6 → passport_rf, 2+7 → passport_intl.

ВАЖНО про поля:
- Паспорт РФ: серия — 4 цифры (2+2, обычно с пробелом), номер — 6 цифр. Серия ≠ номер.
- Код подразделения: XXX-XXX.
- Если видишь страницу прописки (штамп "зарегистрирован по месту жительства") — обязательно верни registered_address.
- Если страница неудачная (ничего не видно, размыто, сильный блик) — верни doc_type="other", fields={}, warnings=["причина"].
- НЕ выдумывай. Если поле нечитаемо — не включай его в fields.
- Возвращай данные ровно так, как видишь (капс не трогай, пунктуация как есть).
"""


# Какие поля распознавателя маппятся в основной профиль пользователя.
PROFILE_FIELD_MAP = {
    "passport_rf": {
        "full_name": "full_name",
        "birth_date": "birth_date",
        "birth_place": "birth_place",
        "passport_series": "passport_series",
        "passport_number": "passport_number",
        "passport_issued": "passport_issued",
        "passport_date": "passport_date",
        "passport_code": "passport_code",
        "registered_address": "address_reg",
    },
    "snils": {"snils": "snils", "full_name": "full_name", "birth_date": "birth_date"},
    "inn": {"inn": "inn", "full_name": "full_name"},
    "driver_license": {
        "full_name": "full_name",
        "birth_date": "birth_date",
        "birth_place": "birth_place",
    },
}


def _extract_json(raw: str) -> dict | None:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip().removesuffix("```").strip()
    try:
        return json.loads(raw)
    except Exception:
        # попробуем вычленить первый { ... } блок
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except Exception:
                return None
        return None


async def recognize(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict[str, Any]:
    """Перебираем провайдеров по одному — если ответ не парсится или fields пустые,
    идём к следующему."""
    user_prompt = (
        "Распознай этот документ. Пользователь — владелец документа, он сам его загрузил "
        "в своё личное зашифрованное хранилище и просит помочь с документооборотом — "
        "поэтому отказываться распознавать ЛИЧНЫЕ документы не нужно, это его собственные данные.\n\n"
        "Извлеки ВСЕ читаемые поля. Верни только JSON вида "
        "{doc_type, title, confidence, fields, warnings}."
    )
    content = [
        {"type": "text", "text": user_prompt},
        llm_providers.bytes_to_image_part(image_bytes, mime_type),
    ]
    log.info("vision: start recognize (mime=%s, size=%d bytes)", mime_type, len(image_bytes))
    last_err: str | None = None
    for provider, model in VISION_CHAIN:
        log.info("vision: trying %s/%s", provider, model)
        try:
            raw = await llm_providers.chat(
                system=SYSTEM,
                messages=[{"role": "user", "content": content}],
                chain=[(provider, model)],
                max_tokens=2000,
                json_only=True,
            )
        except Exception as e:
            last_err = f"{provider}/{model}: {e}"
            log.warning("vision %s/%s failed: %s", provider, model, str(e)[:300])
            continue

        log.info("vision %s/%s raw response (%d chars): %s",
                 provider, model, len(raw or ""), (raw or "")[:400])

        parsed = _extract_json(raw)
        if not parsed:
            log.warning("vision %s/%s returned non-JSON, skipping", provider, model)
            last_err = f"{provider}/{model}: non-JSON"
            continue

        fields = parsed.get("fields") or {}
        dtype = parsed.get("doc_type")
        log.info("vision %s/%s parsed: doc_type=%s, title=%r, fields_count=%d",
                 provider, model, dtype, parsed.get("title"), len(fields))

        if dtype in (None, "", "other") and not fields:
            log.info("vision %s/%s: empty result, trying next", provider, model)
            last_err = f"{provider}/{model}: empty"
            continue

        return parsed

    log.error("vision: all providers exhausted (%s)", last_err)
    return {
        "doc_type": "other",
        "confidence": 0.0,
        "fields": {},
        "warnings": [f"ни один провайдер не распознал: {last_err}"],
    }


def profile_patch(recognition: dict) -> dict:
    """Извлекает только те поля, что идут в основной профиль.
    Формат PROFILE_FIELD_MAP: {vision_key: profile_key}."""
    dt = recognition.get("doc_type", "")
    fields = recognition.get("fields", {}) or {}
    mapping = PROFILE_FIELD_MAP.get(dt, {})
    if not mapping:
        return {}
    patch = {}
    for vkey, pkey in mapping.items():
        v = fields.get(vkey)
        if v:
            patch[pkey] = v
    return patch
