import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "")
OWNER_TG_ID = int(os.environ.get("OWNER_TG_ID", "0") or 0)

ALLOWED_TG_IDS: set[int] = {
    int(x) for x in os.environ.get("ALLOWED_TG_IDS", "").split(",") if x.strip().isdigit()
}
if OWNER_TG_ID:
    ALLOWED_TG_IDS.add(OWNER_TG_ID)


def owner_id(tg_id: int) -> int:
    """Возвращает канонический owner_id. Все твои аккаунты → один OWNER_TG_ID,
    так профиль/vault/history — общие. Чужие (если просочатся) — остаются собой."""
    if tg_id in ALLOWED_TG_IDS:
        return OWNER_TG_ID or tg_id
    return tg_id

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# Порядок попыток для текстовой генерации (право РФ — нужна сильная модель)
LLM_CHAIN = [
    ("openai", "gpt-5.1"),
    ("openai", "gpt-4.1"),
    ("gemini_browser", "gemini-2.5-pro"),
    ("openai", "gpt-4o"),
    ("openrouter", "anthropic/claude-opus-4"),
    ("openrouter", "anthropic/claude-sonnet-4"),
    ("anthropic", "claude-opus-4-7"),
]
LLM_CHAIN_FAST = [
    ("openai", "gpt-4.1-mini"),
    ("gemini_browser", "gemini-2.0-flash"),
    ("openai", "gpt-4o-mini"),
    ("groq", "llama-3.3-70b-versatile"),
]
VISION_CHAIN = [
    ("openrouter", "anthropic/claude-sonnet-4"),
    ("openrouter", "google/gemini-2.5-pro"),
    ("openai", "gpt-4o"),
    ("openai", "gpt-4.1"),
    ("openrouter", "anthropic/claude-opus-4"),
    ("anthropic", "claude-opus-4-7"),
]

DB_PATH = ROOT / "bot.db"
TEMPLATES_DIR = ROOT / "templates"
STORAGE_DIR = ROOT / "storage" / "generated"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

DOC_PAGE_STYLE = {
    "paper": "A4",
    "font_family": "Times New Roman, serif",
    "font_size_pt": 12,
    "margin_top_cm": 2.0,
    "margin_right_cm": 1.0,
    "margin_bottom_cm": 2.0,
    "margin_left_cm": 3.0,
    "line_height": 1.3,
}
