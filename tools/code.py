from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .filesystem import is_ignored_path, relative_path, resolve_workspace_path

DEFAULT_MAX_SYMBOL_RESULTS = 50
SOURCE_SUFFIXES = {".go", ".java", ".js", ".jsx", ".kt", ".md", ".py", ".rs", ".sh", ".ts", ".tsx"}
SYMBOL_PATTERNS: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    ".py": [
        ("function", re.compile(r"^\s*(?:async\s+def|def)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")),
        ("class", re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
    ],
    ".go": [
        ("function", re.compile(r"^\s*func\s+(?:\([^)]+\)\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*\(")),
        ("type", re.compile(r"^\s*type\s+([A-Za-z_][A-Za-z0-9_]*)\s+(?:struct|interface)\b")),
    ],
    ".rs": [
        ("function", re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")),
        ("struct", re.compile(r"^\s*(?:pub\s+)?struct\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
        ("enum", re.compile(r"^\s*(?:pub\s+)?enum\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
        ("trait", re.compile(r"^\s*(?:pub\s+)?trait\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
    ],
    ".js": [
        ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(")),
        ("class", re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)\b")),
        ("value", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=")),
        ("type", re.compile(r"^\s*(?:export\s+)?type\s+([A-Za-z_$][A-Za-z0-9_$]*)\b")),
        ("interface", re.compile(r"^\s*(?:export\s+)?interface\s+([A-Za-z_$][A-Za-z0-9_$]*)\b")),
    ],
    ".jsx": [
        ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(")),
        ("class", re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)\b")),
        ("value", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=")),
    ],
    ".ts": [
        ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(")),
        ("class", re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)\b")),
        ("value", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=")),
        ("type", re.compile(r"^\s*(?:export\s+)?type\s+([A-Za-z_$][A-Za-z0-9_$]*)\b")),
        ("interface", re.compile(r"^\s*(?:export\s+)?interface\s+([A-Za-z_$][A-Za-z0-9_$]*)\b")),
    ],
    ".tsx": [
        ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(")),
        ("class", re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)\b")),
        ("value", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=")),
    ],
    ".java": [
        ("class", re.compile(r"^\s*(?:public\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
        ("interface", re.compile(r"^\s*(?:public\s+)?interface\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
        ("enum", re.compile(r"^\s*(?:public\s+)?enum\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
        ("method", re.compile(r"^\s*(?:public|protected|private)?(?:\s+static)?(?:\s+final)?\s+[A-Za-z_<>\[\], ?]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")),
    ],
    ".kt": [
        ("class", re.compile(r"^\s*(?:public\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
        ("object", re.compile(r"^\s*(?:public\s+)?object\s+([A-Za-z_][A-Za-z0-9_]*)\b")),
        ("function", re.compile(r"^\s*(?:public\s+)?fun\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")),
    ],
    ".sh": [
        ("function", re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{")),
    ],
}
for suffix in (".jsx", ".tsx"):
    SYMBOL_PATTERNS.setdefault(suffix, SYMBOL_PATTERNS[".js"])


def search_symbols(
    query: str,
    *,
    path: str = ".",
    max_results: int = DEFAULT_MAX_SYMBOL_RESULTS,
    case_sensitive: bool = False,
    include_hidden: bool = False,
) -> dict[str, Any]:
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("query must not be empty")

    target = resolve_workspace_path(path)
    if not target.exists():
        raise ValueError(f"path does not exist: {path}")

    limit = max(1, min(int(max_results), 500))
    needle = normalized_query if case_sensitive else normalized_query.lower()
    matches: list[dict[str, Any]] = []

    for file_path in iter_files(target, include_hidden=include_hidden):
        if len(matches) >= limit:
            break
        if file_path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        try:
            lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, start=1):
            if len(matches) >= limit:
                break
            symbol_hit = extract_symbol(file_path, line)
            if symbol_hit is None:
                continue
            symbol_name, kind = symbol_hit
            haystack = symbol_name if case_sensitive else symbol_name.lower()
            line_haystack = line if case_sensitive else line.lower()
            if needle not in haystack and needle not in line_haystack:
                continue
            matches.append(
                {
                    "path": relative_path(file_path),
                    "line": line_no,
                    "symbol": symbol_name,
                    "kind": kind,
                    "text": line.strip(),
                }
            )

    return {"query": normalized_query, "match_count": len(matches), "matches": matches}


def edit_file(path: str, old: str, new: str, *, replace_all: bool = False) -> dict[str, Any]:
    target = resolve_workspace_path(path)
    if not target.is_file():
        raise ValueError(f"path is not a file: {path}")
    if old == "":
        raise ValueError("old must not be empty")

    original = target.read_text(encoding="utf-8")
    occurrences = original.count(old)
    if occurrences == 0:
        raise ValueError("old text was not found")
    if not replace_all and occurrences != 1:
        raise ValueError(f"old text matched {occurrences} times; set replace_all=true to replace all matches")

    updated = original.replace(old, new) if replace_all else original.replace(old, new, 1)
    target.write_text(updated, encoding="utf-8")
    return {
        "path": relative_path(target),
        "replacements": occurrences if replace_all else 1,
        "bytes_before": len(original.encode("utf-8")),
        "bytes_after": len(updated.encode("utf-8")),
    }


def iter_files(target: Path, *, include_hidden: bool) -> list[Path]:
    if target.is_file():
        return [target]
    files: list[Path] = []
    for item in target.rglob("*"):
        if not item.is_file() or is_ignored_path(item):
            continue
        if not include_hidden and any(part.startswith(".") for part in item.relative_to(target).parts):
            continue
        files.append(item)
    return files


def extract_symbol(path: Path, line: str) -> tuple[str, str] | None:
    suffix = path.suffix.lower()
    for kind, pattern in SYMBOL_PATTERNS.get(suffix, []):
        match = pattern.match(line)
        if match:
            return match.group(1), kind
    if suffix == ".md":
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if heading:
            return heading.group(1), "heading"
    return None
