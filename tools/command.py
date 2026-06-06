from __future__ import annotations

import shlex
import subprocess
from typing import Any

from .filesystem import resolve_workspace_path, workspace_root

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_OUTPUT_BYTES = 120_000
MAX_UNCOMPRESSED_LINES = 160
IMPORTANT_LINE_MARKERS = (
    "error",
    "failed",
    "failure",
    "traceback",
    "exception",
    "warning",
    "assert",
    "passed",
    "collected",
    "short test summary",
    "syntaxerror",
)

ALLOWED_EXACT_PREFIXES = (
    ("python", "-m", "py_compile"),
    ("python3", "-m", "py_compile"),
    ("python", "-m", "pytest"),
    ("python3", "-m", "pytest"),
    ("pytest",),
    ("git", "status"),
    ("git", "diff"),
    ("git", "log"),
)

SHELL_COMMAND_PREFIXES = (
    ("bash", "-lc"),
    ("sh", "-lc"),
    ("zsh", "-lc"),
)

BLOCKED_TOKENS = {
    "rm",
    "rmdir",
    "mv",
    "cp",
    "sudo",
    "su",
    "chmod",
    "chown",
    "curl",
    "wget",
    "ssh",
    "scp",
    "fish",
}


def run_command(
    command: str | list[str],
    *,
    cwd: str = ".",
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    compress_output: bool = True,
) -> dict[str, Any]:
    args = parse_command(command)
    validate_command(args)
    workdir = resolve_workspace_path(cwd)
    if not workdir.is_dir():
        raise ValueError(f"cwd is not a directory: {cwd}")

    completed = subprocess.run(
        args,
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=max(1, min(int(timeout), 120)),
        check=False,
    )
    stdout, stdout_truncated, stdout_compressed = prepare_output(completed.stdout, max_output_bytes, compress_output)
    stderr, stderr_truncated, stderr_compressed = prepare_output(completed.stderr, max_output_bytes, compress_output)
    return {
        "command": args,
        "cwd": str(workdir.relative_to(workspace_root())),
        "returncode": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "stdout_compressed": stdout_compressed,
        "stderr_compressed": stderr_compressed,
    }


def command_requires_approval(command: str | list[str]) -> bool:
    args = parse_command(command)
    return any(tuple(args[: len(prefix)]) == prefix for prefix in SHELL_COMMAND_PREFIXES)


def parse_command(command: str | list[str]) -> list[str]:
    args = shlex.split(command) if isinstance(command, str) else [str(item) for item in command]
    if not args:
        raise ValueError("command must not be empty")
    return args


def validate_command(args: list[str]) -> None:
    executable = args[0]
    if executable in BLOCKED_TOKENS:
        raise ValueError(f"command is blocked: {executable}")
    if any(token in {"&&", "||", ";", "|", ">", ">>", "<"} for token in args):
        raise ValueError("shell operators are not allowed")
    allowed_prefixes = ALLOWED_EXACT_PREFIXES + SHELL_COMMAND_PREFIXES
    if not any(tuple(args[: len(prefix)]) == prefix for prefix in allowed_prefixes):
        allowed = ", ".join(" ".join(prefix) for prefix in allowed_prefixes)
        raise ValueError(f"command is not allowed. Allowed prefixes: {allowed}")


def prepare_output(text: str, max_bytes: int, compress_output: bool) -> tuple[str, bool, bool]:
    compressed = False
    if compress_output:
        text, compressed = compress_text(text)
    text, truncated = truncate_text(text, max_bytes)
    return text, truncated, compressed


def compress_text(text: str) -> tuple[str, bool]:
    lines = text.splitlines()
    if len(lines) <= MAX_UNCOMPRESSED_LINES:
        return text, False

    important = []
    seen_indexes = set()
    for index, line in enumerate(lines):
        lowered = line.lower()
        if any(marker in lowered for marker in IMPORTANT_LINE_MARKERS):
            important.append((index, line))
            seen_indexes.add(index)
        if len(important) >= 80:
            break

    selected: list[str] = []
    selected.extend(lines[:40])
    if important:
        selected.append(f"...[{len(lines) - 80} middle lines compressed; important lines below]...")
        for index, line in important:
            selected.append(f"{index + 1}: {line}")
    else:
        selected.append(f"...[{len(lines) - 80} middle lines compressed]...")
    tail_start = max(40, len(lines) - 40)
    selected.extend(line for index, line in enumerate(lines[tail_start:], start=tail_start) if index not in seen_indexes)
    return "\n".join(selected), True


def truncate_text(text: str, max_bytes: int) -> tuple[str, bool]:
    limit = max(1, min(int(max_bytes), 1_000_000))
    if len(text.encode("utf-8")) <= limit:
        return text, False
    truncated = text.encode("utf-8")[: max(0, limit - 32)].decode("utf-8", errors="ignore")
    return truncated + "...[truncated]", True
