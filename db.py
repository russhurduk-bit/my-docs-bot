"""SQLite: профили пользователей + история сгенерированных документов."""
import json
from pathlib import Path
from typing import Any

import aiosqlite

from config import DB_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id            INTEGER PRIMARY KEY,
    full_name        TEXT,
    birth_date       TEXT,
    birth_place      TEXT,
    passport_series  TEXT,
    passport_number  TEXT,
    passport_issued  TEXT,
    passport_date    TEXT,
    passport_code    TEXT,
    inn              TEXT,
    snils            TEXT,
    address_reg      TEXT,
    address_live     TEXT,
    phone            TEXT,
    email            TEXT,
    extra_json       TEXT DEFAULT '{}',
    updated_at       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id       INTEGER NOT NULL,
    title       TEXT,
    doc_type    TEXT,
    pdf_path    TEXT,
    input_data  TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS dialogs (
    tg_id       INTEGER PRIMARY KEY,
    state_json  TEXT DEFAULT '{}',
    updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS vault_files (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id          INTEGER NOT NULL,
    doc_type       TEXT,
    title          TEXT,
    original_name  TEXT,
    enc_path       TEXT NOT NULL,
    mime_type      TEXT,
    size_bytes     INTEGER,
    sha256         TEXT,
    ocr_data       TEXT DEFAULT '{}',
    note           TEXT,
    created_at     TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_vault_user ON vault_files(tg_id);
CREATE INDEX IF NOT EXISTS idx_vault_sha  ON vault_files(tg_id, sha256);

CREATE TABLE IF NOT EXISTS pending_docs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id        INTEGER NOT NULL,
    title        TEXT,
    doc_type     TEXT,
    html         TEXT,
    law_refs     TEXT,
    notes        TEXT,
    preview_path TEXT,
    created_at   TEXT DEFAULT (datetime('now'))
);
"""

PROFILE_FIELDS = [
    "full_name", "birth_date", "birth_place",
    "passport_series", "passport_number", "passport_issued",
    "passport_date", "passport_code",
    "inn", "snils",
    "address_reg", "address_live",
    "phone", "email",
]


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def get_profile(tg_id: int) -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        row = await cur.fetchone()
        if not row:
            return {"tg_id": tg_id}
        data = dict(row)
        data["extra"] = json.loads(data.pop("extra_json") or "{}")
        return data


async def upsert_profile(tg_id: int, patch: dict[str, Any]) -> None:
    current = await get_profile(tg_id)
    extras = current.get("extra", {})
    fields = {}
    for k, v in patch.items():
        if k in PROFILE_FIELDS:
            fields[k] = v
        else:
            extras[k] = v

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (tg_id) VALUES (?)", (tg_id,)
        )
        if fields:
            cols = ", ".join(f"{k} = ?" for k in fields)
            await db.execute(
                f"UPDATE users SET {cols}, updated_at = datetime('now') WHERE tg_id = ?",
                (*fields.values(), tg_id),
            )
        await db.execute(
            "UPDATE users SET extra_json = ?, updated_at = datetime('now') WHERE tg_id = ?",
            (json.dumps(extras, ensure_ascii=False), tg_id),
        )
        await db.commit()


async def add_history(tg_id: int, title: str, doc_type: str, pdf_path: str, input_data: dict) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO history (tg_id, title, doc_type, pdf_path, input_data) VALUES (?, ?, ?, ?, ?)",
            (tg_id, title, doc_type, str(pdf_path), json.dumps(input_data, ensure_ascii=False)),
        )
        await db.commit()
        return cur.lastrowid


async def list_history(tg_id: int, limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM history WHERE tg_id = ? ORDER BY id DESC LIMIT ?",
            (tg_id, limit),
        )
        return [dict(r) for r in await cur.fetchall()]


async def get_dialog_state(tg_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT state_json FROM dialogs WHERE tg_id = ?", (tg_id,))
        row = await cur.fetchone()
        return json.loads(row[0]) if row and row[0] else {}


async def set_dialog_state(tg_id: int, state: dict) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO dialogs (tg_id, state_json) VALUES (?, ?) "
            "ON CONFLICT(tg_id) DO UPDATE SET state_json = excluded.state_json, updated_at = datetime('now')",
            (tg_id, json.dumps(state, ensure_ascii=False)),
        )
        await db.commit()


async def clear_dialog_state(tg_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM dialogs WHERE tg_id = ?", (tg_id,))
        await db.commit()
