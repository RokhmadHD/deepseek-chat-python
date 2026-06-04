from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
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


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


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
