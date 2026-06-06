from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

from .logging_config import get_logger
from .session_store import DEFAULT_PROFILE, StoredSession, load_session

log = get_logger("client")
DEFAULT_SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "settings" / "system.md"
DEFAULT_MAX_TOOL_ROUNDS = 4
DEFAULT_TOOL_RESULT_MAX_BYTES = 120_000
DEFAULT_RUN_COMMAND_PROMPT_MAX_BYTES = 8_000
ToolEventCallback = Callable[[dict[str, Any]], None]
ToolApprovalDecision = str
ToolApprovalCallback = Callable[[str, dict[str, Any]], ToolApprovalDecision]


def env_bool(name: str, fallback: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return fallback
    return raw.lower() in {"1", "true", "yes", "on"}


def execute_registered_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        from tools import execute_tool
    except ModuleNotFoundError:
        project_root = Path(__file__).resolve().parents[1]
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        from tools import execute_tool
    return execute_tool(name, arguments)


def command_requires_approval(command: str | list[str]) -> bool:
    try:
        from tools.command import command_requires_approval as helper
    except ModuleNotFoundError:
        project_root = Path(__file__).resolve().parents[1]
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        from tools.command import command_requires_approval as helper
    try:
        return helper(command)
    except Exception:
        log.exception("failed to classify command approval requirement")
        return True


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


def parse_tool_message(text: str) -> dict[str, Any] | None:
    stripped = strip_code_fence(text.strip())
    if not stripped:
        return None
    parse_candidates = [stripped]
    compact = stripped.lstrip()
    if compact.startswith('"type"'):
        wrapped = stripped
        if not compact.startswith("{"):
            wrapped = "{" + wrapped
        if not wrapped.rstrip().endswith("}"):
            wrapped += "}"
        parse_candidates.append(wrapped)
    parsed: Any = None
    for candidate in parse_candidates:
        try:
            parsed = json.loads(candidate)
            break
        except json.JSONDecodeError:
            continue
    if parsed is None:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def normalize_assistant_text(text: str) -> str:
    message = parse_tool_message(text)
    if not message:
        return text
    if message.get("type") != "response":
        return text
    content = message.get("content")
    return content if isinstance(content, str) else string_value(content)


def strip_code_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) >= 3 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def string_value(value: Any) -> str:
    return value if isinstance(value, str) else ""


def summarize_tool_result(result: dict[str, Any]) -> str:
    if "result_count" in result:
        return f"{result.get('result_count')} results"
    if "match_count" in result:
        return f"{result.get('match_count')} matches"
    if "change_count" in result:
        return f"{result.get('change_count')} changes"
    if "bytes" in result:
        return f"{result.get('bytes')} bytes"
    if "content" in result:
        return f"{len(string_value(result.get('content')))} chars"
    return "ok"


def tool_result_excerpt(text: str, max_bytes: int) -> str:
    if not text:
        return ""
    if len(text.encode("utf-8")) <= max_bytes:
        return text
    return truncate_text(text, max_bytes)


def truncate_text(text: str, max_bytes: int) -> str:
    if len(text.encode("utf-8")) <= max_bytes:
        return text
    encoded = text.encode("utf-8")[: max(0, max_bytes - 40)]
    return encoded.decode("utf-8", errors="ignore") + "...[truncated]"


@dataclass
class ChatTurn:
    text: str
    session_id: str
    parent_message_id: str | int | None
    raw: str
    tool_events: list[dict[str, Any]] = field(default_factory=list)


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
        self.system_prompt_enabled = env_bool("DEEPSEEK_SYSTEM_PROMPT_ENABLED", True)
        self.system_prompt_path = Path(os.getenv("DEEPSEEK_SYSTEM_PROMPT_PATH", str(DEFAULT_SYSTEM_PROMPT_PATH)))
        self.system_prompt = self.load_system_prompt()
        self.max_tool_rounds = int(os.getenv("DEEPSEEK_MAX_TOOL_ROUNDS", str(DEFAULT_MAX_TOOL_ROUNDS)))
        self.tool_result_max_bytes = int(os.getenv("DEEPSEEK_TOOL_RESULT_MAX_BYTES", str(DEFAULT_TOOL_RESULT_MAX_BYTES)))
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
        if not isinstance(data, dict):
            raise RuntimeError(f"DeepSeek returned invalid chat session payload: {data!r}")
        payload = data.get("data")
        if not isinstance(payload, dict):
            raise RuntimeError(f"DeepSeek returned invalid chat session payload: {data!r}")
        biz_data = payload.get("biz_data")
        if not isinstance(biz_data, dict):
            raise RuntimeError(f"DeepSeek returned invalid chat session payload: {data!r}")
        session = biz_data.get("chat_session")
        if not isinstance(session, dict):
            raise RuntimeError(f"DeepSeek returned invalid chat session payload: {data!r}")
        session_id = session.get("id")
        if not session_id:
            raise RuntimeError(f"DeepSeek returned no chat session: {data}")
        return str(session_id)

    def load_system_prompt(self) -> str:
        if not self.system_prompt_enabled:
            return ""
        try:
            return self.system_prompt_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            log.warning("system prompt file not found path=%s", self.system_prompt_path)
            return ""

    def prompt_for_request(self, prompt: str, *, is_new_session: bool) -> str:
        if not is_new_session or not self.system_prompt:
            return prompt
        return (
            "<SYSTEM_INSTRUCTIONS>\n"
            f"{self.system_prompt}\n"
            "</SYSTEM_INSTRUCTIONS>\n\n"
            "<USER_MESSAGE>\n"
            f"{prompt}\n"
            "</USER_MESSAGE>"
        )

    def chat_with_tools(
        self,
        prompt: str,
        session_id: str | None = None,
        parent_message_id: str | int | None = None,
        ref_file_ids: list[str] | None = None,
        on_tool_event: ToolEventCallback | None = None,
        on_tool_approval: ToolApprovalCallback | None = None,
    ) -> ChatTurn:
        turn = self.chat(prompt, session_id=session_id, parent_message_id=parent_message_id, ref_file_ids=ref_file_ids)
        tool_events: list[dict[str, Any]] = []

        for _round in range(max(0, self.max_tool_rounds)):
            message = parse_tool_message(turn.text)
            if message is None:
                turn.tool_events = tool_events
                return turn

            message_type = message.get("type")
            if message_type == "response":
                turn.text = string_value(message.get("content"))
                turn.tool_events = tool_events
                return turn

            if message_type != "tool_call":
                turn.text = f"Invalid tool response type: {message_type}"
                turn.tool_events = tool_events
                return turn

            tool_name = string_value(message.get("tool"))
            arguments = message.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}

            call_event = {"type": "tool_call", "tool": tool_name, "arguments": arguments}
            tool_events.append(call_event)
            if on_tool_event:
                on_tool_event(call_event)
            approval_denied = False
            needs_approval = tool_name == "write_file"
            if tool_name == "run_command":
                needs_approval = command_requires_approval(arguments.get("command", []))
            if needs_approval:
                try:
                    approval = "deny" if on_tool_approval is None else on_tool_approval(tool_name, arguments)
                except Exception:
                    log.exception("tool approval failed tool=%s", tool_name)
                    approval = "deny"
                approval_denied = approval == "deny"

            started_at = time.perf_counter()
            try:
                if approval_denied:
                    raise PermissionError(f"{tool_name} denied by user")
                result = execute_registered_tool(tool_name, arguments)
                tool_payload = self.tool_followup_payload(tool_name, result, ok=True)
                result_event = {
                    "type": "tool_result",
                    "tool": tool_name,
                    "ok": True,
                    "summary": summarize_tool_result(result),
                    "elapsed": time.perf_counter() - started_at,
                }
                tool_events.append(result_event)
                if on_tool_event:
                    on_tool_event(result_event)
            except PermissionError as exc:
                result_event = {
                    "type": "tool_result",
                    "tool": tool_name,
                    "ok": False,
                    "summary": str(exc),
                    "elapsed": 0.0,
                }
                tool_events.append(result_event)
                if on_tool_event:
                    on_tool_event(result_event)
                tool_payload = {"ok": False, "error": str(exc)}
            except Exception as exc:
                log.exception("tool execution failed tool=%s", tool_name)
                result_event = {
                    "type": "tool_result",
                    "tool": tool_name,
                    "ok": False,
                    "summary": str(exc),
                    "elapsed": time.perf_counter() - started_at,
                }
                tool_events.append(result_event)
                if on_tool_event:
                    on_tool_event(result_event)
                tool_payload = {"ok": False, "error": str(exc)}

            followup_prompt = self.tool_result_prompt(tool_name, arguments, tool_payload)
            turn = self.chat(
                followup_prompt,
                session_id=turn.session_id,
                parent_message_id=turn.parent_message_id,
                ref_file_ids=ref_file_ids,
            )

        turn.tool_events = tool_events
        return turn

    def tool_followup_payload(self, tool_name: str, result: dict[str, Any], *, ok: bool) -> dict[str, Any]:
        if tool_name != "run_command":
            return {"ok": ok, "result": result}

        payload: dict[str, Any] = {
            "ok": ok,
            "summary": summarize_tool_result(result),
            "returncode": result.get("returncode"),
            "command": result.get("command"),
            "cwd": result.get("cwd"),
            "stdout_truncated": bool(result.get("stdout_truncated")),
            "stderr_truncated": bool(result.get("stderr_truncated")),
            "stdout_compressed": bool(result.get("stdout_compressed")),
            "stderr_compressed": bool(result.get("stderr_compressed")),
        }
        if env_bool("DEEPSEEK_TOOL_RESULT_INCLUDE_OUTPUT", False):
            payload["stdout"] = tool_result_excerpt(string_value(result.get("stdout")), DEFAULT_RUN_COMMAND_PROMPT_MAX_BYTES)
            payload["stderr"] = tool_result_excerpt(string_value(result.get("stderr")), DEFAULT_RUN_COMMAND_PROMPT_MAX_BYTES)
        return payload

    def tool_result_prompt(self, tool_name: str, arguments: dict[str, Any], payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            {
                "tool": tool_name,
                "arguments": arguments,
                **payload,
            },
            ensure_ascii=False,
            default=str,
        )
        encoded = truncate_text(encoded, self.tool_result_max_bytes)
        extra_guidance = ""
        if tool_name == "run_command":
            extra_guidance = (
                "Do not quote stdout or stderr verbatim unless the user explicitly asked for command output. "
                "Use the summary, return code, command, and cwd to decide the next step. "
            )
        return (
            "<TOOL_RESULT>\n"
            f"{encoded}\n"
            "</TOOL_RESULT>\n\n"
            f"{extra_guidance}Return the next valid JSON object now. If this result answers the user, return a response object. "
            "If another tool is required, return one tool_call object."
        )

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
        is_new_session = session_id is None and parent_message_id is None
        session_id = session_id or self.create_session()
        request_prompt = self.prompt_for_request(prompt, is_new_session=is_new_session)
        challenge = self.get_pow_challenge()
        pow_response = self.solve_pow(challenge)
        response = self.client.post(
            f"{self.api_base}/api/v0/chat/completion",
            headers=self.headers({"x-ds-pow-response": pow_response}, referer_session_id=session_id),
            json={
                "chat_session_id": session_id,
                "parent_message_id": parent_message_id,
                "model_type": self.model_type,
                "prompt": request_prompt,
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
            text=normalize_assistant_text(render_sse_text(raw)),
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
