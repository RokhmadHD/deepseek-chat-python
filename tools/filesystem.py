from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

WORKSPACE_ROOT_ENV = "TOOL_WORKSPACE_ROOT"
DEFAULT_MAX_READ_BYTES = 200_000
DEFAULT_MAX_ENTRIES = 200
DEFAULT_MAX_SEARCH_RESULTS = 100
DEFAULT_TREE_DEPTH = 3
AUTO_MAP_THRESHOLD_BYTES = 80_000
MAP_LINE_RE = re.compile(
    r"^(\s*)(class|def|async def|from|import)\s+([A-Za-z_][A-Za-z0-9_\.]*|[A-Za-z_][A-Za-z0-9_]*\s+import\b|[A-Za-z_][A-Za-z0-9_]*\b)"
)


def list_dir(path: str = ".", *, max_entries: int = DEFAULT_MAX_ENTRIES) -> dict[str, Any]:
    target = resolve_workspace_path(path)
    if not target.is_dir():
        raise ValueError(f"path is not a directory: {path}")

    entries = []
    for item in sorted(target.iterdir(), key=lambda entry: (not entry.is_dir(), entry.name.lower()))[:max_entries]:
        entries.append(
            {
                "name": item.name,
                "path": relative_path(item),
                "type": "directory" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
            }
        )
    return {"path": relative_path(target), "entry_count": len(entries), "entries": entries}


def tree_dir(
    path: str = ".",
    *,
    max_depth: int = DEFAULT_TREE_DEPTH,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    include_hidden: bool = False,
) -> dict[str, Any]:
    target = resolve_workspace_path(path)
    if not target.is_dir():
        raise ValueError(f"path is not a directory: {path}")

    limit = clamp_int(max_entries, minimum=1, maximum=1_000)
    depth = clamp_int(max_depth, minimum=1, maximum=10)
    lines = [relative_path(target) or "."]
    count = 0

    def visible_children(directory: Path) -> list[Path]:
        children = []
        for child in sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            if not include_hidden and child.name.startswith("."):
                continue
            if is_ignored_path(child):
                continue
            children.append(child)
        return children

    def walk(directory: Path, prefix: str, current_depth: int) -> None:
        nonlocal count
        if current_depth > depth or count >= limit:
            return
        children = visible_children(directory)
        for index, child in enumerate(children):
            if count >= limit:
                lines.append(f"{prefix}└── ...")
                return
            connector = "└── " if index == len(children) - 1 else "├── "
            lines.append(f"{prefix}{connector}{child.name}")
            count += 1
            if child.is_dir():
                extension = "    " if index == len(children) - 1 else "│   "
                walk(child, prefix + extension, current_depth + 1)

    walk(target, "", 1)
    return {
        "path": relative_path(target),
        "max_depth": depth,
        "entry_count": count,
        "truncated": count >= limit,
        "tree": "\n".join(lines),
    }


def read_file(path: str, *, max_bytes: int = DEFAULT_MAX_READ_BYTES, mode: str = "auto") -> dict[str, Any]:
    target = resolve_workspace_path(path)
    if not target.is_file():
        raise ValueError(f"path is not a file: {path}")

    limit = clamp_int(max_bytes, minimum=1, maximum=2_000_000)
    data = target.read_bytes()
    selected_mode = normalize_read_mode(mode, len(data))
    text = data.decode("utf-8", errors="replace")
    if selected_mode.startswith("lines:"):
        content, truncated = read_line_range(text, selected_mode, limit)
    elif selected_mode == "map":
        content, truncated = read_map(text, limit)
    else:
        truncated = len(data) > limit
        content = data[:limit].decode("utf-8", errors="replace")
    return {
        "path": relative_path(target),
        "bytes": len(data),
        "mode": selected_mode,
        "truncated": truncated,
        "content": content,
    }


def normalize_read_mode(mode: str, byte_count: int) -> str:
    normalized = (mode or "auto").strip().lower()
    if normalized == "auto":
        return "map" if byte_count > AUTO_MAP_THRESHOLD_BYTES else "full"
    if normalized in {"full", "map"} or normalized.startswith("lines:"):
        return normalized
    raise ValueError("mode must be one of: auto, full, map, lines:N-M")


def read_line_range(text: str, mode: str, max_bytes: int) -> tuple[str, bool]:
    raw_range = mode.removeprefix("lines:")
    if "-" not in raw_range:
        raise ValueError("line mode must use lines:N-M")
    start_raw, end_raw = raw_range.split("-", 1)
    start = clamp_int(int(start_raw), minimum=1, maximum=10_000_000)
    end = clamp_int(int(end_raw), minimum=start, maximum=10_000_000)
    lines = text.splitlines()
    selected = lines[start - 1 : end]
    numbered = "\n".join(f"{line_no:4}| {line}" for line_no, line in enumerate(selected, start=start))
    return clamp_content(numbered, max_bytes)


def read_map(text: str, max_bytes: int) -> tuple[str, bool]:
    lines = text.splitlines()
    mapped: list[str] = []
    skipped = 0
    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        match = MAP_LINE_RE.match(line)
        if match:
            mapped.append(f"{line_no:4}| {line}")
            skipped = 0
            continue
        if stripped.startswith(("#", "@")):
            mapped.append(f"{line_no:4}| {line}")
            skipped = 0
            continue
        if not stripped:
            skipped += 1
            continue
        if skipped == 0 and mapped:
            mapped.append("     ...")
        skipped += 1
    if not mapped:
        mapped = lines[:80]
    return clamp_content("\n".join(mapped), max_bytes)


def clamp_content(text: str, max_bytes: int) -> tuple[str, bool]:
    limit = clamp_int(max_bytes, minimum=1, maximum=2_000_000)
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text, False
    truncated = encoded[: max(0, limit - 32)].decode("utf-8", errors="ignore")
    return truncated + "...[truncated]", True


def write_file(
    path: str,
    content: str,
    *,
    create_dirs: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    target = resolve_workspace_path(path)
    existed = target.exists()
    if create_dirs:
        target.parent.mkdir(parents=True, exist_ok=True)
    elif not target.parent.exists():
        raise ValueError(f"parent directory does not exist: {relative_path(target.parent)}")
    if existed and not overwrite:
        raise ValueError(f"file already exists: {relative_path(target)}")
    target.write_text(content, encoding="utf-8")
    return {"path": relative_path(target), "bytes": len(content.encode("utf-8")), "overwritten": existed}


def search_files(
    query: str,
    *,
    path: str = ".",
    max_results: int = DEFAULT_MAX_SEARCH_RESULTS,
    case_sensitive: bool = False,
) -> dict[str, Any]:
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("query must not be empty")

    target = resolve_workspace_path(path)
    if not target.exists():
        raise ValueError(f"path does not exist: {path}")

    limit = clamp_int(max_results, minimum=1, maximum=500)
    command = ["rg", "--line-number", "--no-heading", "--color", "never", "--max-count", str(limit)]
    if not case_sensitive:
        command.append("--ignore-case")
    command.extend([normalized_query, str(target)])
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return search_files_python(normalized_query, target, limit=limit, case_sensitive=case_sensitive)

    if completed.returncode not in {0, 1}:
        raise RuntimeError(completed.stderr.strip() or "rg failed")

    matches = []
    for line in completed.stdout.splitlines()[:limit]:
        file_path, line_number, text = parse_rg_line(line)
        matches.append({"path": relative_path(Path(file_path)), "line": line_number, "text": text})
    return {"query": normalized_query, "match_count": len(matches), "matches": matches}


def search_files_python(query: str, target: Path, *, limit: int, case_sensitive: bool) -> dict[str, Any]:
    matches = []
    needle = query if case_sensitive else query.lower()
    files = [target] if target.is_file() else [item for item in target.rglob("*") if item.is_file()]
    for file_path in files:
        if is_ignored_path(file_path):
            continue
        try:
            lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for index, line in enumerate(lines, start=1):
            haystack = line if case_sensitive else line.lower()
            if needle in haystack:
                matches.append({"path": relative_path(file_path), "line": index, "text": line})
                if len(matches) >= limit:
                    return {"query": query, "match_count": len(matches), "matches": matches}
    return {"query": query, "match_count": len(matches), "matches": matches}


def resolve_workspace_path(path: str) -> Path:
    root = workspace_root()
    target = (root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"path is outside workspace: {path}")
    return target


def workspace_root() -> Path:
    return Path(os.getenv(WORKSPACE_ROOT_ENV, Path.cwd())).resolve()


def relative_path(path: Path) -> str:
    return str(path.resolve().relative_to(workspace_root()))


def parse_rg_line(line: str) -> tuple[str, int, str]:
    file_path, line_number, text = line.split(":", 2)
    return file_path, int(line_number), text


def is_ignored_path(path: Path) -> bool:
    return any(part in {".git", ".venv", "__pycache__", ".cache"} for part in path.parts)


def clamp_int(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))
