from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .code import edit_file, search_symbols
from .command import run_command
from .context import project_overview
from .filesystem import list_dir, read_file, search_files, tree_dir, write_file
from .project import git_diff, git_log, git_status
from .searxng import multi_search, search_web
from .utility import calculate, format_json, get_time, json_validate

ToolHandler = Callable[..., dict[str, Any]]

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "search_web",
        "description": "Search the web through the configured SearXNG instance.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "max_results": {"type": "integer", "default": 5},
                "language": {"type": "string", "default": "en"},
                "categories": {"type": "string"},
                "time_range": {"type": "string", "description": "day, week, month, or year."},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "multi_search",
        "description": "Run multiple SearXNG searches and deduplicate URLs for deep search.",
        "parameters": {
            "type": "object",
            "properties": {
                "queries": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
                "max_results_per_query": {"type": "integer", "default": 5},
                "language": {"type": "string", "default": "en"},
                "categories": {"type": "string"},
                "time_range": {"type": "string", "description": "day, week, month, or year."},
            },
            "required": ["queries"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_dir",
        "description": "List files and directories inside the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "."},
                "max_entries": {"type": "integer", "default": 200},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "project_overview",
        "description": "Return a compact project map with a tree and task-relevant files.",
        "parameters": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "default": ""},
                "max_files": {"type": "integer", "default": 16},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "search_symbols",
        "description": "Find code symbols such as functions, classes, and types in workspace files.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "path": {"type": "string", "default": "."},
                "max_results": {"type": "integer", "default": 50},
                "case_sensitive": {"type": "boolean", "default": False},
                "include_hidden": {"type": "boolean", "default": False},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file inside the workspace with optional context-saving modes.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_bytes": {"type": "integer", "default": 200000},
                "mode": {
                    "type": "string",
                    "default": "auto",
                    "description": "auto, full, map, or lines:N-M.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "write_file",
        "description": "Create or update a file inside the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": { "type": "string" },
                "content": { "type": "string" },
                "overwrite": { "type": "boolean", "default": False },
                "create_dirs": { "type": "boolean", "default": False },
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "edit_file",
        "description": "Replace a unique text snippet in a workspace file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old": {"type": "string"},
                "new": {"type": "string"},
                "replace_all": {"type": "boolean", "default": False},
            },
            "required": ["path", "old", "new"],
            "additionalProperties": False,
        },
    },
    {
        "name": "tree_dir",
        "description": "Return a tree view of files and directories inside the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "."},
                "max_depth": {"type": "integer", "default": 3},
                "max_entries": {"type": "integer", "default": 200},
                "include_hidden": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "search_files",
        "description": "Search text inside workspace files.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "path": {"type": "string", "default": "."},
                "max_results": {"type": "integer", "default": 100},
                "case_sensitive": {"type": "boolean", "default": False},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "git_status",
        "description": "Return git status --short for the workspace.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "git_diff",
        "description": "Return git diff for the workspace or one path.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_bytes": {"type": "integer", "default": 200000},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "git_log",
        "description": "Return recent git commits.",
        "parameters": {
            "type": "object",
            "properties": {"max_count": {"type": "integer", "default": 10}},
            "additionalProperties": False,
        },
    },
    {
        "name": "run_command",
        "description": "Run an allowlisted command in the workspace without shell operators.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ]
                },
                "cwd": {"type": "string", "default": "."},
                "timeout": {"type": "integer", "default": 30},
                "max_output_bytes": {"type": "integer", "default": 120000},
                "compress_output": {"type": "boolean", "default": True},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_time",
        "description": "Return the current UTC time.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "json_validate",
        "description": "Validate whether text is parseable JSON.",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "format_json",
        "description": "Pretty-print JSON text.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "indent": {"type": "integer", "default": 2},
                "sort_keys": {"type": "boolean", "default": False},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "calculate",
        "description": "Evaluate a simple arithmetic expression.",
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
            "additionalProperties": False,
        },
    },
]

TOOL_HANDLERS: dict[str, ToolHandler] = {
    "search_web": search_web,
    "multi_search": multi_search,
    "list_dir": list_dir,
    "project_overview": project_overview,
    "search_symbols": search_symbols,
    "read_file": read_file,
    "edit_file": edit_file,
    "write_file": write_file,
    "tree_dir": tree_dir,
    "search_files": search_files,
    "git_status": git_status,
    "git_diff": git_diff,
    "git_log": git_log,
    "run_command": run_command,
    "get_time": get_time,
    "json_validate": json_validate,
    "format_json": format_json,
    "calculate": calculate,
}


def execute_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"unknown tool: {name}")
    return handler(**(arguments or {}))
