"""Единый асинхронный интерфейс к нескольким LLM-провайдерам.

chat(system, messages, chain, max_tokens, json_only) — пробует провайдеров по
цепочке, первый успешный ответ возвращает. messages: [{"role": "...", "content": "..."}].

Для vision — messages могут содержать image parts, формат OpenAI-совместимый:
[{"role":"user","content":[{"type":"text","text":"..."}, {"type":"image_url","image_url":{"url":"data:image/jpeg;base64,..."}}]}]
"""
import asyncio
import base64
import logging
import os
from typing import Any

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from config import (
    ANTHROPIC_API_KEY,
    GEMINI_API_KEY,
    GROQ_API_KEY,
    OPENAI_API_KEY,
    OPENROUTER_API_KEY,
)

log = logging.getLogger(__name__)

_openai = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
_anthropic = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
_openrouter = AsyncOpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
) if OPENROUTER_API_KEY else None
_groq = AsyncOpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
) if GROQ_API_KEY else None
_gemini = AsyncOpenAI(
    api_key=GEMINI_API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
) if GEMINI_API_KEY else None

# Локальный OpenAI-совместимый прокси к gemini.google.com (round-robin аккаунтов).
# Бесплатный, поддерживает vision. Адрес задаётся через env.
GEMINI_BROWSER_URL = os.environ.get("GEMINI_BROWSER_URL", "http://127.0.0.1:8891/v1")
_gemini_browser = AsyncOpenAI(api_key="local-proxy", base_url=GEMINI_BROWSER_URL)


def _uses_max_completion_tokens(model: str) -> bool:
    """Новые модели OpenAI (gpt-5.x, o1, o3, gpt-4.1) используют max_completion_tokens."""
    m = model.lower()
    return (
        m.startswith("gpt-5")
        or m.startswith("o1")
        or m.startswith("o3")
        or m.startswith("o4")
        or m.startswith("gpt-4.1")
    )


async def _call_openai_like(client: AsyncOpenAI, model: str, system: str, messages: list[dict],
                            max_tokens: int, json_only: bool) -> str:
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)
    kwargs: dict[str, Any] = {"model": model, "messages": msgs}
    if _uses_max_completion_tokens(model):
        kwargs["max_completion_tokens"] = max_tokens
    else:
        kwargs["max_tokens"] = max_tokens
    if json_only:
        kwargs["response_format"] = {"type": "json_object"}
    resp = await client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


async def _call_anthropic(model: str, system: str, messages: list[dict], max_tokens: int) -> str:
    # Перегоняем OpenAI-формат сообщений в Anthropic
    ant_msgs = []
    for m in messages:
        role = "user" if m["role"] == "user" else "assistant"
        content = m["content"]
        if isinstance(content, list):
            ant_parts = []
            for p in content:
                if p.get("type") == "text":
                    ant_parts.append({"type": "text", "text": p["text"]})
                elif p.get("type") == "image_url":
                    url = p["image_url"]["url"] if isinstance(p["image_url"], dict) else p["image_url"]
                    if url.startswith("data:"):
                        header, b64 = url.split(",", 1)
                        media = header.split(";")[0].replace("data:", "")
                        ant_parts.append({"type": "image", "source": {
                            "type": "base64", "media_type": media, "data": b64,
                        }})
            content = ant_parts
        ant_msgs.append({"role": role, "content": content})

    resp = await _anthropic.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system or "",
        messages=ant_msgs,
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


async def chat(
    system: str,
    messages: list[dict],
    chain: list[tuple[str, str]],
    max_tokens: int = 4000,
    json_only: bool = False,
) -> str:
    """Пробует провайдеров по цепочке. Возвращает текст первого успешного."""
    last_err: Exception | None = None
    for provider, model in chain:
        try:
            if provider == "openai" and _openai:
                return await _call_openai_like(_openai, model, system, messages, max_tokens, json_only)
            if provider == "anthropic" and _anthropic:
                return await _call_anthropic(model, system, messages, max_tokens)
            if provider == "openrouter" and _openrouter:
                return await _call_openai_like(_openrouter, model, system, messages, max_tokens, json_only)
            if provider == "groq" and _groq:
                return await _call_openai_like(_groq, model, system, messages, max_tokens, json_only)
            if provider == "gemini" and _gemini:
                return await _call_openai_like(_gemini, model, system, messages, max_tokens, json_only)
            if provider == "gemini_browser":
                return await _call_openai_like(_gemini_browser, model, system, messages, max_tokens, json_only)
        except Exception as e:
            last_err = e
            msg = str(e)[:200]
            log.warning("LLM %s/%s failed: %s", provider, model, msg)
            continue
    raise RuntimeError(f"All LLM providers failed; last error: {last_err}")


def bytes_to_image_part(raw: bytes, mime: str = "image/jpeg") -> dict:
    b64 = base64.b64encode(raw).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
