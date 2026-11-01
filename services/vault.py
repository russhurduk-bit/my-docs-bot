"""Шифрованное хранилище сканов. AES-256-GCM; VAULT_KEY обязателен."""
import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Optional

import aiosqlite
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from config import DB_PATH, ROOT

VAULT_ROOT = ROOT / "storage" / "vault"
VAULT_ROOT.mkdir(parents=True, exist_ok=True)
def _load_key() -> bytes:
    key_b64 = os.environ.get("VAULT_KEY")
    if not key_b64:
        raise RuntimeError("VAULT_KEY is required; generate it once and keep it in a private .env file")
    try:
        key = base64.b64decode(key_b64, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise RuntimeError("VAULT_KEY must be base64-encoded") from exc
    if len(key) != 32:
        raise RuntimeError("VAULT_KEY must decode to 32 bytes")
    return key


_KEY = _load_key()
_aes = AESGCM(_KEY)


def _user_dir(tg_id: int) -> Path:
    p = VAULT_ROOT / str(tg_id)
    p.mkdir(parents=True, exist_ok=True)
    # запрет доступа для других — 0700
    try:
        os.chmod(p, 0o700)
    except Exception:
        pass
    return p


async def find_by_hash(tg_id: int, sha: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, doc_type, title, original_name, created_at FROM vault_files "
            "WHERE tg_id = ? AND sha256 = ? LIMIT 1",
            (tg_id, sha),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def find_semantic_duplicate(tg_id: int, doc_type: str, fields: dict) -> Optional[dict]:
    """Ищет уже загруженный документ того же смысла по ключевым полям."""
    if not fields or doc_type in (None, "", "other"):
        return None

    key_fields = {
        "passport_rf": ("passport_series", "passport_number"),
        "passport_intl": ("passport_series", "passport_number"),
        "snils": ("snils",),
        "inn": ("inn",),
        "driver_license": ("driver_license_number",),
        "vehicle_reg": ("vin", "license_plate"),
    }.get(doc_type)

    if not key_fields:
        return None
    vals = [fields.get(k) for k in key_fields if fields.get(k)]
    if not vals:
        return None

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        conds = ["doc_type = ?"]
        params: list = [doc_type]
        for v in vals:
            conds.append("ocr_data LIKE ?")
            params.append(f"%{v}%")
        sql = (
            "SELECT id, title, created_at FROM vault_files "
            "WHERE tg_id = ? AND " + " AND ".join(conds) + " ORDER BY id DESC LIMIT 1"
        )
        cur = await db.execute(sql, (tg_id, *params))
        row = await cur.fetchone()
        return dict(row) if row else None


async def store_file(
    tg_id: int,
    raw_bytes: bytes,
    original_name: str,
    mime_type: str,
    doc_type: Optional[str] = None,
    title: Optional[str] = None,
    ocr_data: Optional[dict] = None,
    note: Optional[str] = None,
    sha256: Optional[str] = None,
) -> int:
    nonce = os.urandom(12)
    ct = _aes.encrypt(nonce, raw_bytes, associated_data=str(tg_id).encode())
    payload = nonce + ct

    udir = _user_dir(tg_id)
    from datetime import datetime
    fname = f"{datetime.now():%Y%m%d_%H%M%S_%f}.enc"
    path = udir / fname
    path.write_bytes(payload)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass

    sha = sha256 or hashlib.sha256(raw_bytes).hexdigest()

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO vault_files (tg_id, doc_type, title, original_name, enc_path, mime_type, size_bytes, sha256, ocr_data, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tg_id, doc_type, title, original_name, str(path), mime_type, len(raw_bytes),
             sha, json.dumps(ocr_data or {}, ensure_ascii=False), note),
        )
        await db.commit()
        return cur.lastrowid


async def read_file(tg_id: int, file_id: int) -> Optional[tuple[bytes, str, str]]:
    """Вернёт (raw_bytes, original_name, mime_type) или None."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM vault_files WHERE id = ? AND tg_id = ?",
            (file_id, tg_id),
        )
        row = await cur.fetchone()
    if not row:
        return None
    payload = Path(row["enc_path"]).read_bytes()
    nonce, ct = payload[:12], payload[12:]
    raw = _aes.decrypt(nonce, ct, associated_data=str(tg_id).encode())
    return raw, row["original_name"], row["mime_type"]


async def list_files(tg_id: int, limit: int = 50) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, doc_type, title, original_name, size_bytes, mime_type, created_at, note "
            "FROM vault_files WHERE tg_id = ? ORDER BY id DESC LIMIT ?",
            (tg_id, limit),
        )
        return [dict(r) for r in await cur.fetchall()]


async def search_files(tg_id: int, query: str, limit: int = 20) -> list[dict]:
    """Поиск по title, doc_type, original_name, note, ocr_data (включая распознанные поля)."""
    q = f"%{query.strip().lower()}%"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, doc_type, title, original_name, size_bytes, mime_type, created_at, note "
            "FROM vault_files WHERE tg_id = ? AND ("
            "LOWER(IFNULL(title,'')) LIKE ? OR "
            "LOWER(IFNULL(doc_type,'')) LIKE ? OR "
            "LOWER(IFNULL(original_name,'')) LIKE ? OR "
            "LOWER(IFNULL(note,'')) LIKE ? OR "
            "LOWER(IFNULL(ocr_data,'')) LIKE ?"
            ") ORDER BY id DESC LIMIT ?",
            (tg_id, q, q, q, q, q, limit),
        )
        return [dict(r) for r in await cur.fetchall()]


async def delete_file(tg_id: int, file_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT enc_path FROM vault_files WHERE id = ? AND tg_id = ?",
            (file_id, tg_id),
        )
        row = await cur.fetchone()
        if not row:
            return False
        try:
            Path(row["enc_path"]).unlink(missing_ok=True)
        except Exception:
            pass
        await db.execute(
            "DELETE FROM vault_files WHERE id = ? AND tg_id = ?",
            (file_id, tg_id),
        )
        await db.commit()
    return True
