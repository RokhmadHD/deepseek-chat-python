from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


def env_bool(name: str, fallback: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return fallback
    return raw.lower() in {"1", "true", "yes", "on"}


def read_cookie_header() -> str:
    if cookie := os.getenv("DEEPSEEK_COOKIE_HEADER"):
        return cookie

    cookie_file = os.getenv("DEEPSEEK_COOKIE_FILE")
    if cookie_file and Path(cookie_file).exists():
        return Path(cookie_file).read_text().strip()

    parts: list[str] = []
    cookie_envs = [
        ("aws-waf-token", "DEEPSEEK_AWS_WAF_TOKEN"),
        (".thumbcache_6b2e5483f9d858d7c661c5e276b6a6ae", "DEEPSEEK_THUMBCACHE"),
        ("smidV2", "DEEPSEEK_SMIDV2"),
        ("ds_session_id", "DEEPSEEK_DS_SESSION_ID"),
    ]
    for cookie_name, env_name in cookie_envs:
        if value := os.getenv(env_name):
            parts.append(f"{cookie_name}={value}")
    return "; ".join(parts)


def likely_content_token(value: str) -> bool:
    if not value:
        return False
    return re.fullmatch(r"(DEFAULT|FINISHED|WIP|SYSTEM|ASSISTANT|USER|null|true|false)", value, re.I) is None


def extract_tokens(payload: str) -> list[str]:
    text = payload.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [text] if likely_content_token(text) else []

    response = parsed.get("v", {}).get("response") if isinstance(parsed.get("v"), dict) else None
    fragments = response.get("fragments") if isinstance(response, dict) else None
    if isinstance(fragments, list):
        return [fragment.get("content", "") for fragment in fragments if isinstance(fragment, dict) and fragment.get("content")]

    if isinstance(parsed.get("v"), str):
        value = parsed["v"]
        if parsed.get("p") == "response/fragments/-1/content" or (not parsed.get("p") and likely_content_token(value)):
            return [value]
    return []


def extract_message_id(raw: str) -> str | None:
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if parsed.get("response_message_id") is not None:
            return str(parsed["response_message_id"])
        response = parsed.get("v", {}).get("response") if isinstance(parsed.get("v"), dict) else None
        if isinstance(response, dict) and response.get("message_id") is not None:
            return str(response["message_id"])
    return None


def render_sse_text(raw: str) -> str:
    event_name = "message"
    data_lines: list[str] = []
    out: list[str] = []

    def flush() -> None:
        nonlocal event_name, data_lines
        if not data_lines:
            event_name = "message"
            return
        if event_name != "close":
            out.extend(extract_tokens("\n".join(data_lines)))
        event_name = "message"
        data_lines = []

    for line in raw.splitlines():
        if not line:
            flush()
        elif line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    flush()
    return "".join(out)


@dataclass
class ChatTurn:
    text: str
    session_id: str
    parent_message_id: str | None
    raw: str


class DeepSeekClient:
    def __init__(self) -> None:
        self.api_base = os.getenv("DEEPSEEK_API_BASE", "https://chat.deepseek.com").rstrip("/")
        self.model_type = os.getenv("DEEPSEEK_MODEL_TYPE", "default")
        self.search_enabled = env_bool("DEEPSEEK_SEARCH_ENABLED", True)
        self.thinking_enabled = env_bool("DEEPSEEK_THINKING_ENABLED", False)
        self.preempt = env_bool("DEEPSEEK_PREEMPT", False)
        self.pow_target_path = os.getenv("DEEPSEEK_POW_TARGET_PATH", "/api/v0/chat/completion")
        self.client = httpx.Client(timeout=httpx.Timeout(120.0, connect=30.0))

    def close(self) -> None:
        self.client.close()

    def headers(self, extra: dict[str, str] | None = None, referer_session_id: str | None = None) -> dict[str, str]:
        referer = f"{self.api_base}/"
        if referer_session_id:
            referer = f"{self.api_base}/a/chat/s/{referer_session_id}"

        headers = {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/json",
            "origin": self.api_base,
            "referer": referer,
            "user-agent": os.getenv(
                "DEEPSEEK_USER_AGENT",
                "Mozilla/5.0 (X11; Linux x86_64; rv:151.0) Gecko/20100101 Firefox/151.0",
            ),
            "x-client-platform": "web",
            "x-client-version": "2.0.0",
            "x-client-locale": "en_US",
            "x-client-timezone-offset": os.getenv("DEEPSEEK_TZ_OFFSET", "25200"),
            "x-app-version": "2.0.0",
        }
        if bearer := os.getenv("DEEPSEEK_BEARER"):
            bearer = bearer.removeprefix("Bearer ").strip()
            headers["authz"] = f"Bearer {bearer}"
            headers["authorization"] = f"Bearer {bearer}"
        if x_hif_leim := os.getenv("DEEPSEEK_X_HIF_LEIM"):
            headers["x-hif-leim"] = x_hif_leim
        if cookie := read_cookie_header():
            headers["cookie"] = cookie
        if extra:
            headers.update(extra)
        return headers

    def create_session(self) -> str:
        response = self.client.post(f"{self.api_base}/api/v0/chat_session/create", headers=self.headers(), json={})
        response.raise_for_status()
        data = response.json()
        session = data.get("data", {}).get("biz_data", {}).get("chat_session", {})
        session_id = session.get("id")
        if not session_id:
            raise RuntimeError(f"DeepSeek returned no chat session: {data}")
        return str(session_id)

    def get_pow_challenge(self) -> dict[str, Any]:
        response = self.client.post(
            f"{self.api_base}/api/v0/chat/create_pow_challenge",
            headers=self.headers(),
            json={"target_path": self.pow_target_path},
        )
        response.raise_for_status()
        data = response.json()
        challenge = data.get("data", {}).get("biz_data", {}).get("challenge")
        if not isinstance(challenge, dict):
            raise RuntimeError(f"DeepSeek returned no PoW challenge: {data}")
        return challenge

    def solve_pow(self, challenge: dict[str, Any]) -> str:
        answer = solve_pow_with_wasm(challenge)
        payload = {
            "algorithm": challenge["algorithm"],
            "challenge": challenge["challenge"],
            "salt": challenge["salt"],
            "answer": answer,
            "signature": challenge["signature"],
            "target_path": challenge["target_path"],
        }
        return base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()

    def chat(self, prompt: str, session_id: str | None = None, parent_message_id: str | None = None) -> ChatTurn:
        session_id = session_id or self.create_session()
        challenge = self.get_pow_challenge()
        pow_response = self.solve_pow(challenge)
        response = self.client.post(
            f"{self.api_base}/api/v0/chat/completion",
            headers=self.headers({"x-ds-pow-response": pow_response}, referer_session_id=session_id),
            json={
                "chat_session_id": session_id,
                "parent_message_id": parent_message_id,
                "model_type": self.model_type,
                "prompt": prompt,
                "ref_file_ids": [],
                "thinking_enabled": self.thinking_enabled,
                "search_enabled": self.search_enabled,
                "action": None,
                "preempt": self.preempt,
            },
        )
        response.raise_for_status()
        raw = response.text
        return ChatTurn(
            text=render_sse_text(raw),
            session_id=session_id,
            parent_message_id=extract_message_id(raw) or parent_message_id,
            raw=raw,
        )


def solve_pow_with_wasm(challenge: dict[str, Any]) -> int:
    import wasmtime

    wasm_path = Path(os.getenv("DEEPSEEK_POW_WASM_CACHE", ".cache/sha3_wasm_bg.7b9ca65ddd.wasm"))
    wasm_path.parent.mkdir(parents=True, exist_ok=True)
    if not wasm_path.exists():
        url = os.getenv(
            "DEEPSEEK_POW_WASM_URL",
            "https://fe-static.deepseek.com/chat/static/sha3_wasm_bg.7b9ca65ddd.wasm",
        )
        with httpx.Client(timeout=60.0) as client:
            response = client.get(url, headers={"accept": "*/*", "referer": "https://chat.deepseek.com/"})
            response.raise_for_status()
            wasm_path.write_bytes(response.content)

    store = wasmtime.Store()
    module = wasmtime.Module.from_file(store.engine, str(wasm_path))
    instance = wasmtime.Instance(store, module, [])
    exports = instance.exports(store)
    memory = exports["memory"]
    malloc = exports["__wbindgen_export_0"]
    stack = exports["__wbindgen_add_to_stack_pointer"]
    try:
        solver = exports["wasm_solve"]
        solver_style = "wasm_solve"
    except KeyError:
        solver = exports["wasm_deepseek_hash_v1"]
        solver_style = "wasm_deepseek_hash_v1"

    def write_string(value: str) -> tuple[int, int]:
        encoded = value.encode()
        ptr = malloc(store, len(encoded), 1)
        memory.write(store, encoded, ptr)
        return ptr, len(encoded)

    salt = f"{challenge['salt']}_{challenge['expire_at']}_"
    difficulty = float(challenge["difficulty"])
    ret_ptr = stack(store, -16)
    challenge_ptr, challenge_len = write_string(str(challenge["challenge"]))
    salt_ptr, salt_len = write_string(salt)
    try:
        if solver_style == "wasm_solve":
            solver(store, ret_ptr, challenge_ptr, challenge_len, salt_ptr, salt_len, difficulty)
        else:
            solver(store, challenge_ptr, challenge_len, salt_ptr, salt_len, difficulty, ret_ptr)
        raw = memory.read(store, ret_ptr, ret_ptr + 16)
    finally:
        stack(store, 16)

    # wasm-bindgen returns a struct { i32 status, padding, f64 nonce }.
    import struct

    nonce = struct.unpack_from("<d", raw, 8)[0]
    if nonce != nonce:
        raise RuntimeError("DeepSeek PoW wasm returned NaN")
    return int(nonce)
