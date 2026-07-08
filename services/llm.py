"""Юрист-документовед: классификация, генерация документов, консультация.

Поверх мультипровайдерного llm_providers. Primary — OpenAI (дешевле и оплачено),
fallback — Claude / Gemini / OpenRouter.
"""
import json
import logging
from typing import Any

from config import LLM_CHAIN, LLM_CHAIN_FAST
from services import llm_providers

log = logging.getLogger(__name__)


SYSTEM_LAWYER = """Ты — опытный юрист-документовед Российской Федерации. Текущий год — 2026.

Твоя задача — помогать готовить юридически корректные документы для любых ситуаций в РФ.

Строгие правила:
1. Работаешь по действующему законодательству РФ: ГК, ГПК, ТК, НК, УК, УПК, КоАП, ЖК, СК, ЗК, ФЗ «О защите прав потребителей», ФЗ «О персональных данных», ФЗ-214, ФЗ-44, ФЗ-223, постановления Правительства РФ, актуальная судебная практика (постановления Пленума ВС).
2. В документе — точные ссылки на статьи (номер, пункт, часть).
3. Реквизиты бери из профиля. Если данных нет — задай вопрос, не выдумывай.
4. Оформление по ГОСТ Р 7.0.97-2016: шапка, реквизиты, тело, дата и подпись.
5. Язык формально-деловой.
6. Подписи/печати не подделывай.
"""


SYSTEM_ROUTER = """Ты маршрутизатор запросов в боте «Мои Документы». Определи намерение и верни JSON.

Намерения:
- "need_doc" — нужен документ (один или несколько)
- "consult" — юридическая консультация, какие доки/шаги
- "fill_profile" — изменить свои данные
- "history" — посмотреть свои документы
- "smalltalk" — приветствие/благодарность/вопрос о возможностях
- "other"

Ответ — СТРОГО JSON:
{"intent": "...", "doc_types": ["..."], "situation_summary": "..."}
"""


async def classify(user_text: str) -> dict[str, Any]:
    raw = await llm_providers.chat(
        system=SYSTEM_ROUTER,
        messages=[{"role": "user", "content": user_text}],
        chain=LLM_CHAIN_FAST,
        max_tokens=300,
        json_only=True,
    )
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1].lstrip("json").strip()
    try:
        return json.loads(raw)
    except Exception:
        log.warning("router bad json: %s", raw[:200])
        return {"intent": "other", "doc_types": [], "situation_summary": user_text[:200]}


async def generate_document_html(
    user_request: str,
    profile: dict,
    known_fields: dict,
    history: list[dict] | None = None,
) -> dict[str, Any]:
    """
    Возвращает JSON:
    {
      "status": "ready"|"need_info",
      "questions": [...],
      "documents": [{"title","doc_type","html","law_refs","notes"}]
    }
    """
    user_block = (
        f"Профиль заявителя:\n{json.dumps(profile, ensure_ascii=False, indent=2, default=str)}\n\n"
        f"Уже собранные данные по ситуации:\n{json.dumps(known_fields, ensure_ascii=False, indent=2, default=str)}\n\n"
        f"Запрос пользователя:\n{user_request}\n\n"
        "Если данных достаточно — сгенерируй все нужные документы (может быть несколько). "
        "Если критически не хватает — задай МИНИМУМ уточняющих вопросов.\n\n"
        "Формат HTML каждого документа: самодостаточный <article class=\"doc\">, "
        "шапка в <header> (кому/от кого — в <div class=\"to-block\">, заголовок в <h1>, "
        "подзаголовок в <h2>), тело в <section>, подпись в <footer>. "
        "Никаких <html>/<body>/<style>. Переносы абзацев — <p>. Подпись в <footer class=\"signature\">.\n\n"
        "Верни СТРОГО JSON без markdown обрамления:\n"
        "{\n"
        "  \"status\": \"ready\" | \"need_info\",\n"
        "  \"questions\": [\"...\"],\n"
        "  \"documents\": [\n"
        "    {\"title\": \"...\", \"doc_type\": \"slug\", \"html\": \"<article class=\\\"doc\\\">...</article>\", \"law_refs\": [\"ст. 454 ГК РФ\", ...], \"notes\": \"куда подавать, срок, госпошлина\"}\n"
        "  ]\n"
        "}"
    )
    messages = list(history or [])
    messages.append({"role": "user", "content": user_block})

    raw = await llm_providers.chat(
        system=SYSTEM_LAWYER,
        messages=messages,
        chain=LLM_CHAIN,
        max_tokens=8000,
        json_only=True,
    )
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip().removesuffix("```").strip()
    try:
        return json.loads(raw)
    except Exception as e:
        log.error("LLM returned invalid JSON (%s): %s", e, raw[:400])
        return {
            "status": "need_info",
            "questions": ["Не смог корректно разобрать запрос. Опиши подробнее что нужно."],
        }


async def consult(user_text: str, profile: dict) -> str:
    block = (
        f"Профиль обратившегося:\n{json.dumps(profile, ensure_ascii=False, indent=2, default=str)}\n\n"
        f"Ситуация: {user_text}\n\n"
        "Дай развёрнутый ответ на простом русском:\n"
        "1) Какие статьи/нормы применимы\n"
        "2) Какие документы нужно подготовить (списком)\n"
        "3) Порядок действий пошагово\n"
        "4) Сроки, куда подавать, госпошлины\n\n"
        "В конце предложи: «Хотите, сгенерирую эти документы прямо сейчас?»"
    )
    return (await llm_providers.chat(
        system=SYSTEM_LAWYER,
        messages=[{"role": "user", "content": block}],
        chain=LLM_CHAIN,
        max_tokens=3000,
    )).strip()


async def apply_profile_to_html(html: str, profile: dict, title: str) -> str:
    """Подстановка профиля в черновик. Возвращает финальный HTML."""
    prof_json = json.dumps(
        {k: v for k, v in profile.items()
         if v and k not in ("tg_id", "extra", "updated_at")},
        ensure_ascii=False, indent=2, default=str,
    )
    prompt = (
        f"Документ «{title}» (HTML-черновик). Подставь реквизиты заявителя/стороны из профиля "
        f"в плейсхолдеры (_____, [ФИО], «___», пустые шаблонные значения). "
        f"Ничего больше не меняй. Верни ТОЛЬКО готовый HTML (<article>...</article>).\n\n"
        f"Профиль:\n{prof_json}\n\nHTML:\n{html}"
    )
    out = await llm_providers.chat(
        system=SYSTEM_LAWYER,
        messages=[{"role": "user", "content": prompt}],
        chain=LLM_CHAIN_FAST,
        max_tokens=8000,
    )
    out = out.strip()
    if out.startswith("```"):
        out = out.split("```", 2)[1]
        if out.startswith("html"):
            out = out[4:]
        out = out.strip().removesuffix("```").strip()
    return out or html
