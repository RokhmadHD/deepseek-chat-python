from __future__ import annotations

import shlex
import subprocess
from typing import Any

from .filesystem import resolve_workspace_path, workspace_root

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_OUTPUT_BYTES = 120_000

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
    "bash",
    "sh",
    "zsh",
    "fish",
}


def run_command(
    command: str | list[str],
    *,
    cwd: str = ".",
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
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
    stdout, stdout_truncated = truncate_text(completed.stdout, max_output_bytes)
    stderr, stderr_truncated = truncate_text(completed.stderr, max_output_bytes)
    return {
        "command": args,
        "cwd": str(workdir.relative_to(workspace_root())),
        "returncode": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
    }


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
    if not any(tuple(args[: len(prefix)]) == prefix for prefix in ALLOWED_EXACT_PREFIXES):
        allowed = ", ".join(" ".join(prefix) for prefix in ALLOWED_EXACT_PREFIXES)
        raise ValueError(f"command is not allowed. Allowed prefixes: {allowed}")


def truncate_text(text: str, max_bytes: int) -> tuple[str, bool]:
    limit = max(1, min(int(max_bytes), 1_000_000))
    if len(text.encode("utf-8")) <= limit:
        return text, False
    truncated = text.encode("utf-8")[: max(0, limit - 32)].decode("utf-8", errors="ignore")
    return truncated + "...[truncated]", True
