from __future__ import annotations

import subprocess
from typing import Any

from .filesystem import resolve_workspace_path, workspace_root


def git_status() -> dict[str, Any]:
    completed = run_git(["status", "--short"])
    changes = [line for line in completed.stdout.splitlines() if line.strip()]
    return {"change_count": len(changes), "changes": changes}


def git_diff(path: str | None = None, *, max_bytes: int = 200_000) -> dict[str, Any]:
    command = ["diff", "--"]
    if path:
        command.append(str(resolve_workspace_path(path)))
    completed = run_git(command)
    content = completed.stdout
    limit = max(1, min(int(max_bytes), 2_000_000))
    return {
        "bytes": len(content.encode("utf-8")),
        "truncated": len(content.encode("utf-8")) > limit,
        "content": content[:limit],
    }


def git_log(*, max_count: int = 10) -> dict[str, Any]:
    count = max(1, min(int(max_count), 100))
    completed = run_git(["log", f"--max-count={count}", "--pretty=format:%h%x09%ad%x09%s", "--date=short"])
    commits = []
    for line in completed.stdout.splitlines():
        commit_hash, date, subject = line.split("\t", 2)
        commits.append({"hash": commit_hash, "date": date, "subject": subject})
    return {"commit_count": len(commits), "commits": commits}


def run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=workspace_root(),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return completed
