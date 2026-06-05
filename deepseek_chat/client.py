from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .logging_config import get_logger
from .session_store import DEFAULT_PROFILE, StoredSession, load_session

log = get_logger("client")


def env_bool(name: str, fallback: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return fallback
    return raw.lower() in {"1", "true", "yes", "on"}


def read_cookie_header(session: StoredSession | None = None) -> str:
    return session.cookie_header if session else ""


def likely_content_token(value: str) -> bool:
    if not value:
        return False
    return re.fullmatch(r"(DEFAULT|FINISHED|WIP|SYSTEM|ASSISTANT|USER|null|true|false)", value, re.I) is None


def extract_tokens(payload: str) -> list[str]:
    text = payload
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [text] if likely_content_token(text.strip()) else []

    response = parsed.get("v", {}).get("response") if isinstance(parsed.get("v"), dict) else None
    fragments = response.get("fragments") if isinstance(response, dict) else None
    if isinstance(fragments, list):
        return [fragment.get("content", "") for fragment in fragments if isinstance(fragment, dict) and fragment.get("content")]

    if isinstance(parsed.get("v"), str):
        value = parsed["v"]
        if parsed.get("p") == "response/fragments/-1/content" or (not parsed.get("p") and likely_content_token(value)):
            return [value]
    return []


def extract_message_id(raw: str) -> str | int | None:
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].removeprefix(" ")
        if not payload or payload == "[DONE]":
            continue
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if parsed.get("response_message_id") is not None:
            return parsed["response_message_id"]
        response = parsed.get("v", {}).get("response") if isinstance(parsed.get("v"), dict) else None
        if isinstance(response, dict) and response.get("message_id") is not None:
            return response["message_id"]
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
            data_lines.append(line[5:].removeprefix(" "))
    flush()
    return "".join(out)


@dataclass
class ChatTurn:
    text: str
    session_id: str
    parent_message_id: str | int | None
    raw: str


@dataclass
class UploadedFile:
    id: str
    file_name: str
    file_size: int
    status: str
    token_usage: int | None = None


class DeepSeekClient:
    def __init__(self, profile: str = DEFAULT_PROFILE) -> None:
        self.profile = profile
        self.stored_session = load_session(profile)
        if self.stored_session:
            log.info("loaded sqlite auth profile=%s captured_at=%s", profile, self.stored_session.captured_at)
        else:
            log.warning("no sqlite auth session found for profile=%s", profile)
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
        bearer = self.stored_session.bearer if self.stored_session else ""
        if bearer:
            bearer = bearer.removeprefix("Bearer ").strip()
            headers["authz"] = f"Bearer {bearer}"
            headers["authorization"] = f"Bearer {bearer}"
        x_hif_leim = self.stored_session.x_hif_leim if self.stored_session else ""
        if x_hif_leim:
            headers["x-hif-leim"] = x_hif_leim
        if cookie := read_cookie_header(self.stored_session):
            headers["cookie"] = cookie
        if extra:
            headers.update(extra)
        return headers

    def create_session(self) -> str:
        log.info("creating chat session profile=%s", self.profile)
        response = self.client.post(f"{self.api_base}/api/v0/chat_session/create", headers=self.headers(), json={})
        log.info("create_session status=%s", response.status_code)
        response.raise_for_status()
        data = response.json()
        session = data.get("data", {}).get("biz_data", {}).get("chat_session", {})
        session_id = session.get("id")
        if not session_id:
            raise RuntimeError(f"DeepSeek returned no chat session: {data}")
        return str(session_id)

    def get_pow_challenge(self, target_path: str | None = None) -> dict[str, Any]:
        target = target_path or self.pow_target_path
        log.info("requesting pow challenge target=%s", target)
        response = self.client.post(
            f"{self.api_base}/api/v0/chat/create_pow_challenge",
            headers=self.headers(),
            json={"target_path": target},
        )
        log.info("pow challenge status=%s", response.status_code)
        response.raise_for_status()
        data = response.json()
        challenge = data.get("data", {}).get("biz_data", {}).get("challenge")
        if not isinstance(challenge, dict):
            raise RuntimeError(f"DeepSeek returned no PoW challenge: {data}")
        return challenge

    def solve_pow(self, challenge: dict[str, Any]) -> str:
        log.info("solving pow algorithm=%s difficulty=%s", challenge.get("algorithm"), challenge.get("difficulty"))
        answer = solve_pow_with_wasm(challenge)
        log.info("pow solved answer=%s", answer)
        payload = {
            "algorithm": challenge["algorithm"],
            "challenge": challenge["challenge"],
            "salt": challenge["salt"],
            "answer": answer,
            "signature": challenge["signature"],
            "target_path": challenge["target_path"],
        }
        return base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()

    def upload_file(self, path: str | Path) -> UploadedFile:
        file_path = Path(path).expanduser().resolve()
        if not file_path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")

        file_size = file_path.stat().st_size
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        challenge = self.get_pow_challenge("/api/v0/file/upload_file")
        pow_response = self.solve_pow(challenge)
        headers = self.headers(
            {
                "x-thinking-enabled": "1" if self.thinking_enabled else "0",
                "x-model-type": self.model_type,
                "x-file-size": str(file_size),
                "x-ds-pow-response": pow_response,
            }
        )
        headers.pop("content-type", None)
        log.info("upload file path=%s size=%s content_type=%s", file_path, file_size, content_type)
        with file_path.open("rb") as file:
            response = self.client.post(
                f"{self.api_base}/api/v0/file/upload_file",
                headers=headers,
                files={"file": (file_path.name, file, content_type)},
            )
        log.info("upload status=%s response_bytes=%s", response.status_code, len(response.content))
        if response.status_code >= 400:
            log.error("upload error status=%s body=%s", response.status_code, response.text[:2000])
        response.raise_for_status()
        return self.parse_uploaded_file(response.json())

    def fetch_file(self, file_id: str) -> UploadedFile:
        response = self.client.get(
            f"{self.api_base}/api/v0/file/fetch_files",
            headers=self.headers(),
            params={"file_ids": file_id},
        )
        log.info("fetch_file status=%s file_id=%s", response.status_code, file_id)
        response.raise_for_status()
        data = response.json()
        files = data.get("data", {}).get("biz_data", {}).get("files", [])
        if not files:
            raise RuntimeError(f"DeepSeek returned no file metadata: {data}")
        return self.parse_file_data(files[0])

    def parse_uploaded_file(self, data: dict[str, Any]) -> UploadedFile:
        file_data = data.get("data", {}).get("biz_data", {})
        if not isinstance(file_data, dict) or not file_data.get("id"):
            raise RuntimeError(f"DeepSeek returned no uploaded file id: {data}")
        return self.parse_file_data(file_data)

    def parse_file_data(self, file_data: dict[str, Any]) -> UploadedFile:
        return UploadedFile(
            id=str(file_data["id"]),
            file_name=str(file_data.get("file_name") or file_data["id"]),
            file_size=int(file_data.get("file_size") or 0),
            status=str(file_data.get("status") or ""),
            token_usage=file_data.get("token_usage") if isinstance(file_data.get("token_usage"), int) else None,
        )

    def chat(
        self,
        prompt: str,
        session_id: str | None = None,
        parent_message_id: str | int | None = None,
        ref_file_ids: list[str] | None = None,
    ) -> ChatTurn:
        log.info("chat request profile=%s session=%s parent=%s prompt_len=%s", self.profile, session_id, parent_message_id, len(prompt))
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
                "ref_file_ids": ref_file_ids or [],
                "thinking_enabled": self.thinking_enabled,
                "search_enabled": self.search_enabled,
                "action": None,
                "preempt": self.preempt,
            },
        )
        log.info("completion status=%s response_bytes=%s", response.status_code, len(response.content))
        if response.status_code >= 400:
            log.error("completion error status=%s body=%s", response.status_code, response.text[:2000])
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
