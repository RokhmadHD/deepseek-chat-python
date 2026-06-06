from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


AUTH_COOKIE_NAMES = {"aws-waf-token", "ds_session_id", "smidV2"}
DEFAULT_PROFILE = "default"


@dataclass(frozen=True)
class StoredSession:
    profile: str
    bearer: str
    cookie_header: str
    aws_waf_token: str
    thumbcache: str
    smidv2: str
    ds_session_id: str
    x_hif_leim: str
    captured_at: str


@dataclass(frozen=True)
class ChatSessionRecord:
    profile: str
    chat_session_id: str
    parent_message_id: str | int | None
    title: str
    preview: str
    turn_count: int
    created_at: str
    updated_at: str
    messages: list[dict[str, str]] = field(default_factory=list)
    stats: dict[str, float | int] = field(default_factory=dict)


def project_root() -> Path:
    return Path(os.getenv("TOOL_WORKSPACE_ROOT", Path.cwd())).resolve()


def default_db_path() -> Path:
    return project_root() / ".data" / "session.db"


def newest_capture(captures_dir: Path | None = None) -> Path | None:
    captures_dir = captures_dir or project_root() / "captures"
    if not captures_dir.exists():
        return None

    candidates = [
        item
        for item in captures_dir.iterdir()
        if item.is_dir()
        and item.name.startswith("deepseek-login-")
        and (item / "storage-state.json").exists()
        and (item / "page-storage.json").exists()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.stat().st_mtime)


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    db_path = db_path or default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            profile TEXT PRIMARY KEY,
            bearer TEXT NOT NULL,
            cookie_header TEXT NOT NULL,
            aws_waf_token TEXT NOT NULL DEFAULT '',
            thumbcache TEXT NOT NULL DEFAULT '',
            smidv2 TEXT NOT NULL DEFAULT '',
            ds_session_id TEXT NOT NULL DEFAULT '',
            x_hif_leim TEXT NOT NULL DEFAULT '',
            page_storage_json TEXT NOT NULL,
            storage_state_json TEXT NOT NULL,
            captured_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_sessions (
            profile TEXT NOT NULL,
            chat_session_id TEXT NOT NULL,
            parent_message_id_json TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            preview TEXT NOT NULL DEFAULT '',
            turn_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            stats_json TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (profile, chat_session_id)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_sessions_profile_updated_at
        ON chat_sessions(profile, updated_at DESC)
        """
    )
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(chat_sessions)").fetchall()
    }
    if "messages_json" not in columns:
        conn.execute("ALTER TABLE chat_sessions ADD COLUMN messages_json TEXT NOT NULL DEFAULT '[]'")
    if "stats_json" not in columns:
        conn.execute("ALTER TABLE chat_sessions ADD COLUMN stats_json TEXT NOT NULL DEFAULT '{}'")
    return conn


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_stored_value(raw: str | None, name: str) -> str:
    if not raw:
        raise RuntimeError(f"{name} not found in page-storage.json")
    parsed = json.loads(raw)
    value = parsed.get("value")
    if not value:
        raise RuntimeError(f"{name} has no value")
    return str(value)


def extract_session_from_capture(capture_dir: Path, profile: str = DEFAULT_PROFILE) -> tuple[StoredSession, str, str]:
    storage_state_text = (capture_dir / "storage-state.json").read_text(encoding="utf-8")
    page_storage_text = (capture_dir / "page-storage.json").read_text(encoding="utf-8")
    storage_state = json.loads(storage_state_text)
    page_storage = json.loads(page_storage_text)
    local_storage = page_storage.get("localStorage", {})
    cookies = storage_state.get("cookies", [])

    token = parse_stored_value(local_storage.get("userToken"), "userToken")
    thumbcache_cookie = next((item for item in cookies if str(item.get("name", "")).startswith(".thumbcache_")), None)

    def cookie_value(name: str) -> str:
        for item in cookies:
            if item.get("name") == name:
                return str(item.get("value", ""))
        return ""

    cookie_header = "; ".join(
        f"{item.get('name')}={item.get('value')}"
        for item in cookies
        if item.get("name") in AUTH_COOKIE_NAMES or str(item.get("name", "")).startswith(".thumbcache_")
    )
    if not cookie_header:
        raise RuntimeError("No DeepSeek cookies found in storage-state.json")

    session = StoredSession(
        profile=profile,
        bearer=token,
        cookie_header=cookie_header,
        aws_waf_token=cookie_value("aws-waf-token"),
        thumbcache=str(thumbcache_cookie.get("value", "")) if thumbcache_cookie else "",
        smidv2=cookie_value("smidV2") or str(local_storage.get("smidV2", "")),
        ds_session_id=cookie_value("ds_session_id"),
        x_hif_leim=str(local_storage.get("x-hif-leim", "")),
        captured_at=datetime.now().isoformat(),
    )
    return session, page_storage_text, storage_state_text


def save_session(
    session: StoredSession,
    page_storage_json: str,
    storage_state_json: str,
    db_path: Path | None = None,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sessions (
                profile,
                bearer,
                cookie_header,
                aws_waf_token,
                thumbcache,
                smidv2,
                ds_session_id,
                x_hif_leim,
                page_storage_json,
                storage_state_json,
                captured_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile) DO UPDATE SET
                bearer = excluded.bearer,
                cookie_header = excluded.cookie_header,
                aws_waf_token = excluded.aws_waf_token,
                thumbcache = excluded.thumbcache,
                smidv2 = excluded.smidv2,
                ds_session_id = excluded.ds_session_id,
                x_hif_leim = excluded.x_hif_leim,
                page_storage_json = excluded.page_storage_json,
                storage_state_json = excluded.storage_state_json,
                captured_at = excluded.captured_at
            """,
            (
                session.profile,
                session.bearer,
                session.cookie_header,
                session.aws_waf_token,
                session.thumbcache,
                session.smidv2,
                session.ds_session_id,
                session.x_hif_leim,
                page_storage_json,
                storage_state_json,
                session.captured_at,
            ),
        )


def save_capture_to_db(capture_dir: Path, profile: str = DEFAULT_PROFILE, db_path: Path | None = None) -> StoredSession:
    session, page_storage_json, storage_state_json = extract_session_from_capture(capture_dir, profile)
    save_session(session, page_storage_json, storage_state_json, db_path)
    return session


def load_session(profile: str = DEFAULT_PROFILE, db_path: Path | None = None) -> StoredSession | None:
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                profile,
                bearer,
                cookie_header,
                aws_waf_token,
                thumbcache,
                smidv2,
                ds_session_id,
                x_hif_leim,
                captured_at
            FROM sessions
            WHERE profile = ?
            """,
            (profile,),
        ).fetchone()
    if not row:
        return None
    return StoredSession(*[str(item or "") for item in row])


def _dump_parent_message_id(parent_message_id: str | int | None) -> str:
    return json.dumps(parent_message_id)


def _load_parent_message_id(raw: str) -> str | int | None:
    return json.loads(raw) if raw else None


def _load_messages(raw: str) -> list[dict[str, str]]:
    if not raw:
        return []
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        return []
    messages: list[dict[str, str]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip()
        text = str(item.get("text", ""))
        if role in {"user", "assistant"} and text:
            messages.append({"role": role, "text": text})
    return messages


def _dump_messages(messages: list[dict[str, str]] | None) -> str:
    if not messages:
        return "[]"
    normalized = [
        {"role": str(item.get("role", "")), "text": str(item.get("text", ""))}
        for item in messages
        if str(item.get("role", "")) in {"user", "assistant"} and str(item.get("text", ""))
    ]
    return json.dumps(normalized, ensure_ascii=False)


def _load_stats(raw: str) -> dict[str, float | int]:
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        return {}
    stats: dict[str, float | int] = {}
    for key, value in parsed.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            stats[str(key)] = value
    return stats


def _dump_stats(stats: dict[str, float | int] | None) -> str:
    if not stats:
        return "{}"
    normalized: dict[str, float | int] = {}
    for key, value in stats.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            normalized[str(key)] = value
    return json.dumps(normalized, ensure_ascii=False)


def list_chat_sessions(profile: str = DEFAULT_PROFILE, db_path: Path | None = None) -> list[ChatSessionRecord]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                profile,
                chat_session_id,
                parent_message_id_json,
                title,
                preview,
                turn_count,
                created_at,
                updated_at,
                messages_json,
                stats_json
            FROM chat_sessions
            WHERE profile = ?
            ORDER BY updated_at DESC, chat_session_id DESC
            """,
            (profile,),
        ).fetchall()
    return [
        ChatSessionRecord(
            profile=str(row[0]),
            chat_session_id=str(row[1]),
            parent_message_id=_load_parent_message_id(str(row[2] or "")),
            title=str(row[3] or ""),
            preview=str(row[4] or ""),
            turn_count=int(row[5] or 0),
            created_at=str(row[6] or ""),
            updated_at=str(row[7] or ""),
            messages=_load_messages(str(row[8] or "")),
            stats=_load_stats(str(row[9] or "")),
        )
        for row in rows
    ]


def load_chat_session(
    chat_session_id: str,
    profile: str = DEFAULT_PROFILE,
    db_path: Path | None = None,
) -> ChatSessionRecord | None:
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                profile,
                chat_session_id,
                parent_message_id_json,
                title,
                preview,
                turn_count,
                created_at,
                updated_at,
                messages_json,
                stats_json
            FROM chat_sessions
            WHERE profile = ? AND chat_session_id = ?
            """,
            (profile, chat_session_id),
        ).fetchone()
    if not row:
        return None
    return ChatSessionRecord(
        profile=str(row[0]),
        chat_session_id=str(row[1]),
        parent_message_id=_load_parent_message_id(str(row[2] or "")),
        title=str(row[3] or ""),
        preview=str(row[4] or ""),
        turn_count=int(row[5] or 0),
        created_at=str(row[6] or ""),
        updated_at=str(row[7] or ""),
        messages=_load_messages(str(row[8] or "")),
        stats=_load_stats(str(row[9] or "")),
    )


def save_chat_session(
    profile: str,
    chat_session_id: str,
    parent_message_id: str | int | None,
    title: str,
    preview: str,
    turn_count: int,
    created_at: str,
    updated_at: str,
    messages: list[dict[str, str]] | None = None,
    stats: dict[str, float | int] | None = None,
    db_path: Path | None = None,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO chat_sessions (
                profile,
                chat_session_id,
                parent_message_id_json,
                title,
                preview,
                turn_count,
                created_at,
                updated_at,
                messages_json,
                stats_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile, chat_session_id) DO UPDATE SET
                profile = excluded.profile,
                parent_message_id_json = excluded.parent_message_id_json,
                title = excluded.title,
                preview = excluded.preview,
                turn_count = excluded.turn_count,
                updated_at = excluded.updated_at,
                messages_json = excluded.messages_json,
                stats_json = excluded.stats_json
            """,
            (
                profile,
                chat_session_id,
                _dump_parent_message_id(parent_message_id),
                title,
                preview,
                turn_count,
                created_at,
                updated_at,
                _dump_messages(messages),
                _dump_stats(stats),
            ),
        )
