from __future__ import annotations

from pathlib import Path
from typing import Any

from .filesystem import is_ignored_path, relative_path, tree_dir, workspace_root

DEFAULT_OVERVIEW_FILES = 16
SOURCE_SUFFIXES = {".py", ".md", ".toml", ".json", ".yaml", ".yml", ".txt"}


def project_overview(task: str = "", *, max_files: int = DEFAULT_OVERVIEW_FILES) -> dict[str, Any]:
    root = workspace_root()
    limit = max(1, min(int(max_files), 50))
    candidates = score_files(root, task)
    files = []
    for score, path in candidates[:limit]:
        files.append(
            {
                "path": relative_path(path),
                "bytes": path.stat().st_size,
                "score": score,
            }
        )
    return {
        "root": str(root),
        "task": task,
        "tree": tree_dir(".", max_depth=3, max_entries=120).get("tree", ""),
        "recommended_files": files,
    }


def score_files(root: Path, task: str) -> list[tuple[int, Path]]:
    terms = [term.lower() for term in task.replace("_", " ").replace("-", " ").split() if len(term) >= 3]
    scored: list[tuple[int, Path]] = []
    for path in root.rglob("*"):
        if not path.is_file() or is_ignored_path(path) or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        rel = relative_path(path).lower()
        score = 1
        if path.name in {"README.md", "pyproject.toml", "AGENTS.md"}:
            score += 8
        if path.name in {"registry.py", "filesystem.py", "command.py", "system.md"}:
            score += 12
        score += sum(3 for term in terms if term in rel)
        scored.append((score, path))
    return sorted(scored, key=lambda item: (-item[0], relative_path(item[1])))
