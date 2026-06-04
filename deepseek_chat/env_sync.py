from __future__ import annotations

import json
from pathlib import Path
from typing import Any


AUTH_COOKIE_NAMES = {"aws-waf-token", "ds_session_id", "smidV2"}


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


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


def set_env_value(env_text: str, key: str, value: str) -> str:
    lines = env_text.splitlines()
    replacement = f"{key}={value}"
    for idx, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[idx] = replacement
            return "\n".join(lines) + "\n"
    if env_text and not env_text.endswith("\n"):
        env_text += "\n"
    return f"{env_text}{replacement}\n"


def sync_env_from_capture(capture_dir: Path | None = None, env_file: Path | None = None) -> dict[str, str]:
    capture_dir = capture_dir or newest_capture()
    if not capture_dir:
        raise RuntimeError("No deepseek-login capture found")

    storage_state = read_json(capture_dir / "storage-state.json")
    page_storage = read_json(capture_dir / "page-storage.json")
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

    updates = {
        "DEEPSEEK_BEARER": token,
        "DEEPSEEK_COOKIE_HEADER": cookie_header,
        "DEEPSEEK_AWS_WAF_TOKEN": cookie_value("aws-waf-token"),
        "DEEPSEEK_THUMBCACHE": str(thumbcache_cookie.get("value", "")) if thumbcache_cookie else "",
        "DEEPSEEK_SMIDV2": cookie_value("smidV2") or str(local_storage.get("smidV2", "")),
        "DEEPSEEK_DS_SESSION_ID": cookie_value("ds_session_id"),
    }

    env_file = env_file or project_root() / ".env"
    env_text = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    for key, value in updates.items():
        env_text = set_env_value(env_text, key, value)
    env_file.write_text(env_text, encoding="utf-8")
    return updates
