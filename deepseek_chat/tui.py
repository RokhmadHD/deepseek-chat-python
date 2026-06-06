from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import shlex
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import random

from dotenv import load_dotenv
from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Markdown, Static

from .client import DeepSeekClient, UploadedFile
from .logging_config import get_logger, project_root, setup_logging
from .session_store import ChatSessionRecord, list_chat_sessions, save_chat_session

log = get_logger("tui")

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
ESTIMATED_CHARS_PER_TOKEN = 4
DEFAULT_OUTPUT_COST_PER_1M_TOKENS_USD = 1.10
ROLE_ICONS = {
    "you": "●",
    "deepseek": "◆",
    "system": "•",
    "error": "×",
}
MODEL_TYPES = ["default", "expert"]
PASTE_SUMMARY_THRESHOLD = 120
COMMANDS = [
    ("/attach", "upload file"),
    ("/clear-files", "clear files"),
    ("/copy", "copy last reply"),
    ("/copy all", "copy transcript"),
    ("/copy last", "copy last reply"),
    ("/copy raw", "export raw transcript"),
    ("/copy user", "copy last user message"),
    ("/exit", "quit"),
    ("/files", "list files"),
    ("/model", "toggle model"),
    ("/model default", "default model"),
    ("/model expert", "expert model"),
    ("/q", "quit"),
    ("/quit", "quit"),
]


LOGOS = (r"""
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠃⠀⠀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣤⣤⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⣀⣴⣶⣶⣶⣴⣿⣯⣶⣶⣾⣧⣾⣿⣿⣿⣿⡆⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢠⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣆⢤⠀⠀⢀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢰⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣘⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣯⢆⡁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣏⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣼⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⠆⠈⠉⠋⠉⠙⠛⠛⠛⠛⢛⣿⣿⠛⠛⠛⠙⠉⠉⠙⠪⠉⠁⠀⠂⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⣄⠀⠀⢴⣄⣦⣴⣄⣀⡀⣠⣭⣿⡀⣀⡀⣠⣦⣴⣠⣆⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⣿⣷⣄⣉⣙⣻⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣭⣍⣉⣁⣼⣷⣿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠟⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡟⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⡻⣿⣿⣿⣿⣿⣟⣹⣿⣿⣿⣯⣙⣿⣿⣿⣿⣿⣿⣿⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢈⡹⢿⣿⣿⣿⡿⠻⣿⣿⣿⠿⠟⢿⣿⣿⣿⣿⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢳⣿⣿⣿⣿⣧⠀⠀⠉⠀⠀⠀⣼⣿⣿⣿⣿⠍⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣿⣟⡿⠛⡏⠀⠀⠀⠀⢠⠀⢈⠻⠟⠻⣯⠆⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢋⠀⠀⠀⠐⠢⠴⣆⣤⠏⠎⠊⠁⠀⠀⠸⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠐⠂⣤⣶⣶⣶⣶⣦⣴⣶⣶⣶⣶⣦⠀⠂⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠛⠉⠛⠙⠋⠉⠁⠙⠛⠙⠋⠉⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠐⡄⠀⠀⠀⠀⠀⣠⣄⣤⣤⣤⣤⣤⣄⠀⠀⠀⠀⠀⠀⠀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣷⠀⠀⠀⠀⠻⠹⠛⠟⠻⠙⠿⠿⠊⠅⠀⠀⠀⠀⠀⡜⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⣆⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣼⡁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠛⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣾⡿⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀

""")


BRAND_BANNER = (
    f"                             ╭{'─' * 25}╮  ",
    "    ▓█████▄ ▓█████ ▓█████  ██▓███    ██████ ▓█████ ▓█████  ██ ▄██▀",
    "    ▒██▀ ██▌▓█   ▀ ▓█   ▀ ▓██░  ██▒▒██    ▒ ▓█   ▀ ▓█   ▀  ██▄██▒",
    "    ░██   █▌▒███   ▒███   ▓██░ ██▓▒░ ▓██▄   ▒███   ▒███   ▓████░",
    "    ░▓█▄   ▌▒▓█  ▄ ▒▓█  ▄ ▒██▄█▓▒ ▒  ▒   ██▒▒▓█  ▄ ▒▓█  ▄ ▓██ ██▄",
    "    ░▒████▓ ░▒████▒░▒████▒▒██▒ ░  ░▒██████▒▒░▒████▒░▒████▒▒██▒ ██▄",
    "    ╚═══▀  ░░ ▒░ ░░░ ▒░ ░▒▓▒░ ░  ░▒ ▒▓▒ ▒ ░░░ ▒░ ░░░ ▒░ ░▒ ▒▒  ▒▓░▀",
    f"            ╰{'─' * 30}╯",
)
COMPACT_BANNER = (
    f"╭{'─' * 25}╮",
    f"│{'DEEPSEEK-TUI':^25}│",
    f"╰{'─' * 25}╯",
)


def center_lines(lines: list[str], width: int) -> list[str]:
    return [line.center(width).rstrip() for line in lines]


def render_welcome(logo: str, target_width: int | None = None) -> str:
    logo_lines = logo.strip("\n").splitlines()
    banner_lines = list(BRAND_BANNER)
    content_width = max(len(line) for line in [*logo_lines, *banner_lines])
    if target_width and target_width < content_width:
        content_width = max(len(line) for line in COMPACT_BANNER)
        logo_lines = []
        banner_lines = list(COMPACT_BANNER)
    width = max(content_width, target_width or 0)
    centered = center_lines(logo_lines + banner_lines, width)
    body = "\n".join(centered)
    return f"[bold cyan]{body}[/]"


random_logo = LOGOS


def compact_text(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "…"


def workspace_root_path() -> Path:
    return Path(os.getenv("TOOL_WORKSPACE_ROOT", str(project_root()))).resolve()


def resolve_workspace_path(path: str) -> Path:
    root = workspace_root_path()
    target = (root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"path is outside workspace: {path}")
    return target


def relative_workspace_path(path: Path) -> str:
    return str(path.resolve().relative_to(workspace_root_path()))


def preview_write_content(content: str, limit: int = 420) -> str:
    preview = "\n".join(content.splitlines()[:8]).strip()
    return compact_text(preview, limit) if preview else "(empty)"


class PromptInput(Input):
    """Single-line input that summarizes large pastes but submits their full text."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.pasted_fragments: list[tuple[str, str]] = []

    def _on_paste(self, event: events.Paste) -> None:
        if event.text:
            self.insert_paste(event.text)
        event.stop()
        event.prevent_default()

    def _on_key(self, event: events.Key) -> None:
        if event.key == "up":
            handler = getattr(self.app, "show_prompt_history_previous", None)
        elif event.key == "down":
            handler = getattr(self.app, "show_prompt_history_next", None)
        else:
            return
        if callable(handler):
            handler()
            event.stop()
            event.prevent_default()

    def action_paste(self) -> None:
        clipboard = self.app.clipboard
        if clipboard:
            self.insert_paste(clipboard)

    def insert_paste(self, text: str) -> None:
        insert = self.paste_marker(text) if self.should_summarize_paste(text) else text.splitlines()[0]
        selection = self.selection
        if selection.is_empty:
            self.insert_text_at_cursor(insert)
        else:
            self.replace(insert, *selection)

    def paste_marker(self, text: str) -> str:
        marker = f"[pasted for {len(text)} chars]"
        self.pasted_fragments.append((marker, text))
        return marker

    def should_summarize_paste(self, text: str) -> bool:
        return len(text) > PASTE_SUMMARY_THRESHOLD or "\n" in text

    def resolved_value(self) -> str:
        resolved = self.value
        for marker, content in self.pasted_fragments:
            resolved = resolved.replace(marker, content, 1)
        return resolved

    def clear_prompt(self) -> None:
        self.value = ""
        self.pasted_fragments.clear()

    def set_prompt_text(self, text: str) -> None:
        self.value = text
        self.pasted_fragments.clear()
        try:
            self.cursor_position = len(text)
        except Exception:
            pass


class WriteFileApprovalScreen(ModalScreen[str | None]):
    CSS = """
    Screen {
        align: center middle;
    }

    #approval-shell {
        width: 78;
        height: auto;
        border: solid $secondary;
        background: $surface;
        padding: 1 2;
    }

    #approval-body {
        height: auto;
        color: $text-muted;
        text-opacity: 75%;
    }

    #approval-list {
        height: auto;
        max-height: 7;
        margin-top: 1;
        border: none;
        background: $surface;
        color: $text-muted 70%;
    }

    ListItem {
        padding: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "deny", "Deny"),
        ("q", "deny", "Deny"),
    ]

    def __init__(self, path: str, directory: str, content: str, overwrite: bool, create_dirs: bool) -> None:
        super().__init__()
        self.path = path
        self.directory = directory
        self.content = content
        self.overwrite = overwrite
        self.create_dirs = create_dirs

    def compose(self) -> ComposeResult:
        with Vertical(id="approval-shell"):
            body = (
                "Approve write_file request\n"
                "Use Up/Down and Enter. Esc or q denies.\n\n"
                f"Path: {self.path}\n"
                f"Directory: {self.directory}\n"
                f"Overwrite: {'yes' if self.overwrite else 'no'}\n"
                f"Create dirs: {'yes' if self.create_dirs else 'no'}\n\n"
                f"Preview:\n{preview_write_content(self.content)}"
            )
            yield Static(body, id="approval-body")
            yield ListView(
                ListItem(Label("Approve once"), id="approve-once"),
                ListItem(Label("Approve this directory"), id="approve-dir"),
                ListItem(Label("Deny"), id="deny"),
                id="approval-list",
            )

    def on_mount(self) -> None:
        approval_list = self.query_one("#approval-list", ListView)
        approval_list.index = 0
        approval_list.focus()

    def action_deny(self) -> None:
        self.dismiss("deny")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        selected_id = event.item.id or ""
        if selected_id == "approve-once":
            self.dismiss("approve_once")
        elif selected_id == "approve-dir":
            self.dismiss("approve_dir")
        elif selected_id == "deny":
            self.dismiss("deny")


class ChatSessionPicker(App[ChatSessionRecord | None]):
    CSS = """
    Screen {
        layout: vertical;
        align: center middle;
    }

    #picker-shell {
        height: auto;
        border: solid $secondary;
        padding: 1 2;
    }

    #picker-body {
        height: auto;
        color: $text-muted;
    }

    ListView {
        height: 1fr;
        border: none;
        background: $surface;
        color: $text-muted 50%;
    }

    ListItem {
        padding: 0 1;
    }
    """

    BINDINGS = [
        ("enter", "choose", "Choose"),
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
    ]

    def __init__(self, profile: str) -> None:
        super().__init__()
        self.profile = profile
        self.sessions: list[ChatSessionRecord] = []
        self.selected_index = 0
        self.picker_populated = False

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-shell"):
            yield Static("Resume chat session\nUse Up/Down and Enter. Esc or q to cancel.\n", id="picker-body")
            yield ListView(id="session-list")

    async def on_mount(self) -> None:
        self.title = "deepseek-chat-python"
        self.sub_title = f"resume profile={self.profile}"
        self.sessions = list_chat_sessions(self.profile)
        if not self.sessions:
            self.exit(None)
            return
        await self.populate_list()
        self.query_one("#session-list", ListView).focus()

    def action_choose(self) -> None:
        if not self.sessions:
            return
        session_list = self.query_one("#session-list", ListView)
        index = session_list.index if session_list.index is not None else self.selected_index
        self.exit(self.sessions[index])

    def action_cancel(self) -> None:
        self.exit(None)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        selected_id = event.item.id or ""
        prefix = "session-"
        if not selected_id.startswith(prefix):
            return
        index = int(selected_id.removeprefix(prefix))
        self.exit(self.sessions[index])

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        selected_id = event.item.id or ""
        prefix = "session-"
        if selected_id.startswith(prefix):
            self.selected_index = int(selected_id.removeprefix(prefix))

    async def populate_list(self) -> None:
        if self.picker_populated:
            return
        session_list = self.query_one("#session-list", ListView)
        await session_list.extend(self.render_item(index, session) for index, session in enumerate(self.sessions))
        session_list.index = 0
        self.picker_populated = True

    def format_relative_time(self, dt_str: str) -> str:
        """Convert ISO datetime string to human readable relative time (e.g., '5s ago', '2m ago')."""
        try:
            # Parsing ISO format, asumsi tanpa timezone info (naive)
            dt = datetime.fromisoformat(dt_str)
        except ValueError:
            return dt_str  # fallback

        now = datetime.now()
        diff = now - dt

        seconds = diff.total_seconds()
        if seconds < 0:
            return "just now"

        if seconds < 60:
            return f"{int(seconds)}s ago"
        minutes = seconds / 60
        if minutes < 60:
            return f"{int(minutes)}m ago"
        hours = minutes / 60
        if hours < 24:
            return f"{int(hours)}h ago"
        days = hours / 24
        if days < 30:
            return f"{int(days)}d ago"
        months = days / 30
        if months < 12:
            return f"{int(months)}mo ago"
        years = days / 365
        return f"{int(years)}y ago"
    def render_item(self, index: int, session: ChatSessionRecord) -> ListItem:
        title = session.title or compact_text(session.preview or session.chat_session_id, 44)
        preview = session.preview or "(no preview)"
        time = self.format_relative_time(session.updated_at)

        meta = f"{session.turn_count} turns > {time}"
        return ListItem(Label(f"[{meta}]{preview}"), id=f"session-{index}")

class DeepSeekTui(App[None]):
    CSS = """
    Screen {
        layout: vertical;
    }

    #workspace {
        height: 1fr;
    }

    #chat {
        height: 1fr;
        width: 1fr;
        border: solid rgb(38, 147, 188);
        padding: 0 1;
        background: $surface;
        scrollbar-size-vertical: 2;
    }

    #stats {
        /* Menggantikan flex-col */
        layout: vertical;

        /* Perbaikan ukuran khusus Textual (Terminal berbasis karakter) */
        height: 100%;             /* Menggantikan 1fr agar memenuhi container parent */
        width: 36;                /* Di Textual, angka tanpa satuan berarti jumlah karakter kolom */
        border: solid $secondary;
        padding: 2;             /* 1 baris vertikal, 2 kolom horizontal */
        color: $text-muted;
        background: $surface;
        text-opacity: 50%;
    }

    #tool-activity {
        height: auto;
        max-height: 18;
        margin-top: 1;
        color: $text-muted;
        text-opacity: 65%;
    }

    #composer {
        height: 4;
        padding: 0;
    }

    #input-info {
        height: auto;
        padding: 0 1;
        color: $text-muted;
        background: rgb(100, 12, 200);
    }

    #prompt {
        width: 1fr;
        border: none;
        padding: 1 2;
        background: $surface;
    }

    #prompt:focus {
        border-left: ascii $secondary;
    }

    .hidden {
        display: none;
    }

    .role {
        text-style: bold;
        margin-top: 0;
        margin-bottom: 0;
    }

    .user-role {
        color: rgb(118, 51, 22);
    }

    .assistant-role {
        color: rgb(41, 155, 191);
    }

    .system-role {
        color: rgb(230, 136, 64);
        text-opacity: 70%;
    }

    .spacing {
        height: 1fr;
    }

    .error-role {
        color: red;
    }

    .bubble {
        margin-bottom: 0;
    }

    .tool-events {
        color: $text-muted;
        text-opacity: 65%;
        margin-top: 0;
        margin-bottom: 0;
    }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear_chat", "Clear"),
    ]

    def __init__(self, profile: str = "default", resume_session: ChatSessionRecord | None = None) -> None:
        super().__init__()
        self.log_file = setup_logging()
        self.profile = profile
        self.client = DeepSeekClient(profile=profile)
        self.session_record = resume_session
        self.session_id: str | None = resume_session.chat_session_id if resume_session else None
        self.parent_message_id: str | int | None = resume_session.parent_message_id if resume_session else None
        self.session_title = resume_session.title if resume_session else ""
        self.session_preview = resume_session.preview if resume_session else ""
        self.session_created_at = resume_session.created_at if resume_session else ""
        self.turn_count = resume_session.turn_count if resume_session else 0
        self.chat_messages = [dict(message) for message in resume_session.messages] if resume_session else []
        session_stats = resume_session.stats if resume_session else {}
        self.pending_prompt = ""
        self.busy = False
        self.loading = False
        self.loading_frame = 0
        self.loading_prefix = "DeepSeek is replying"
        self.current_stream_role: Static | None = None
        self.current_stream_widget: Markdown | None = None
        self.scroll_pending = False
        self.response_count = int(session_stats.get("response_count", 0))
        self.total_output_tokens = int(session_stats.get("total_output_tokens", 0))
        self.total_estimated_cost = float(session_stats.get("total_estimated_cost", 0.0))
        self.last_elapsed = float(session_stats.get("last_elapsed", 0.0))
        self.last_output_tokens = int(session_stats.get("last_output_tokens", 0))
        self.last_tokens_per_second = float(session_stats.get("last_tokens_per_second", 0.0))
        self.last_estimated_cost = float(session_stats.get("last_estimated_cost", 0.0))
        self.attached_files: list[UploadedFile] = []
        self.approved_write_dirs: set[str] = set()
        self.tool_activity_events: list[dict[str, Any]] = []
        self.prompt_history = self.load_prompt_history()
        self.prompt_history_index: int | None = None
        self.prompt_history_draft = ""

    def compose(self) -> ComposeResult:
        with Horizontal(id="workspace"):
            yield VerticalScroll(id="chat")
            with Vertical(id="stats"):
                yield Static(self.stats_text(), id="stats-info")
                yield Static(self.tool_activity_text(), id="tool-activity")
                yield Static("", classes="spacing")                # Pendorong Tengah (1fr)
                # yield Static(self.commands_text(), id="stats-cmds")
        with Vertical(id="composer"):
            yield PromptInput(placeholder="Type message, /attach path, /files, /model, /quit", id="prompt", max_length=2000000)
            yield Static(self.input_info_text(), id="input-info")

    def on_mount(self) -> None:
        log.info("tui mounted profile=%s", self.profile)
        self.title = "deepseek-chat-python"
        self.sub_title = self.model_label()
        if self.session_record:
            self.title = f"deepseek-chat-python - {compact_text(self.session_label(), 24)}"
        self.query_one("#prompt", PromptInput).focus()
        self.set_interval(1, self.update_input_info)
        self.set_interval(1, self.update_stats)
        self.set_stats_visibility(self.size.width)
        if self.session_record:
            self.render_chat_history()
            self.write_system(f"Resumed session: {self.session_label()}")
        chat = self.query_one("#chat", VerticalScroll)
        ascii_art = Static(render_welcome(random_logo, chat.size.width), markup=True, classes="bubble", id="welcome")
        chat.mount(ascii_art)
        self.write_system("Type a message and press Enter. Use /model to switch model_type.")

    def on_click(self) -> None:
        self.query_one("#prompt", PromptInput).focus()

    def on_resize(self, event: object) -> None:
        size = getattr(event, "size", None)
        width = getattr(size, "width", self.size.width)
        self.set_stats_visibility(width)
        try:
            chat_width = self.query_one("#chat", VerticalScroll).size.width
            self.query_one("#welcome", Static).update(render_welcome(random_logo, chat_width))
        except Exception:
            pass

    def on_unmount(self) -> None:
        log.info("tui unmount")
        self.client.close()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        prompt_input = event.input
        display_prompt = event.value.strip()
        prompt = prompt_input.resolved_value().strip() if isinstance(prompt_input, PromptInput) else display_prompt
        if not prompt:
            if isinstance(prompt_input, PromptInput):
                prompt_input.clear_prompt()
            else:
                prompt_input.value = ""
            return
        if prompt in {"/q", "/quit", "/exit"}:
            if isinstance(prompt_input, PromptInput):
                prompt_input.clear_prompt()
            else:
                prompt_input.value = ""
            self.exit()
            return
        if prompt == "/files":
            if isinstance(prompt_input, PromptInput):
                prompt_input.clear_prompt()
            else:
                prompt_input.value = ""
            self.write_attached_files()
            return
        if prompt == "/clear-files":
            if isinstance(prompt_input, PromptInput):
                prompt_input.clear_prompt()
            else:
                prompt_input.value = ""
            self.attached_files.clear()
            self.update_stats()
            self.write_system("Cleared attached files.")
            return
        if prompt == "/copy" or prompt.startswith("/copy "):
            if isinstance(prompt_input, PromptInput):
                prompt_input.clear_prompt()
            else:
                prompt_input.value = ""
            self.handle_copy_command(prompt)
            return
        if prompt.startswith("/attach "):
            if self.busy:
                self.write_system("Request is still running. Wait for the current reply first.")
                return
            if isinstance(prompt_input, PromptInput):
                prompt_input.clear_prompt()
            else:
                prompt_input.value = ""
            try:
                parts = shlex.split(prompt)
            except ValueError as exc:
                self.write_system(f"Invalid /attach command: {exc}")
                return
            if len(parts) != 2:
                self.write_system("Usage: /attach /path/to/file")
                return
            path = parts[1]
            self.busy = True
            self.start_loader("Uploading file")
            self.upload_file(path)
            return
        if prompt == "/model" or prompt.startswith("/model "):
            if isinstance(prompt_input, PromptInput):
                prompt_input.clear_prompt()
            else:
                prompt_input.value = ""
            log.info("model command=%s", prompt)
            self.handle_model_command(prompt)
            return
        if self.busy:
            self.write_system("Request is still running. Wait for the current reply first.")
            return

        if isinstance(prompt_input, PromptInput):
            prompt_input.clear_prompt()
        else:
            prompt_input.value = ""
        self.write_user(display_prompt)
        self.chat_messages.append({"role": "user", "text": display_prompt})
        self.append_prompt_history(prompt)
        self.pending_prompt = prompt
        self.tool_activity_events = []
        self.update_tool_activity()
        self.busy = True
        self.create_assistant_stream()
        self.start_loader("DeepSeek is replying")
        log.info("submitting prompt len=%s", len(prompt))
        self.send_prompt(prompt, [file.id for file in self.attached_files])

    def on_input_changed(self, event: Input.Changed) -> None:
        self.update_input_info(event.value)

    def load_prompt_history(self) -> list[str]:
        history: list[str] = []
        try:
            sessions = list_chat_sessions(self.profile)
        except Exception:
            log.exception("failed to load prompt history")
            return history
        for session in reversed(sessions):
            for message in session.messages:
                if message.get("role") == "user":
                    self.append_prompt_history_text(history, str(message.get("text") or ""))
        return history

    def append_prompt_history(self, prompt: str) -> None:
        self.append_prompt_history_text(self.prompt_history, prompt)
        self.prompt_history_index = None
        self.prompt_history_draft = ""

    def append_prompt_history_text(self, history: list[str], prompt: str) -> None:
        normalized = prompt.strip()
        if not normalized or normalized.startswith("/"):
            return
        try:
            history.remove(normalized)
        except ValueError:
            pass
        history.append(normalized)

    def show_prompt_history_previous(self) -> None:
        if not self.prompt_history:
            return
        prompt_input = self.query_one("#prompt", PromptInput)
        if self.prompt_history_index is None:
            self.prompt_history_draft = prompt_input.resolved_value()
            self.prompt_history_index = len(self.prompt_history) - 1
        elif self.prompt_history_index > 0:
            self.prompt_history_index -= 1
        prompt_input.set_prompt_text(self.prompt_history[self.prompt_history_index])
        self.update_input_info(prompt_input.value)

    def show_prompt_history_next(self) -> None:
        if self.prompt_history_index is None:
            return
        prompt_input = self.query_one("#prompt", PromptInput)
        if self.prompt_history_index < len(self.prompt_history) - 1:
            self.prompt_history_index += 1
            prompt_input.set_prompt_text(self.prompt_history[self.prompt_history_index])
        else:
            self.prompt_history_index = None
            prompt_input.set_prompt_text(self.prompt_history_draft)
            self.prompt_history_draft = ""
        self.update_input_info(prompt_input.value)

    @work(thread=True)
    def send_prompt(self, prompt: str, ref_file_ids: list[str]) -> None:
        started_at = time.perf_counter()
        try:
            turn = self.client.chat_with_tools(
                prompt,
                session_id=self.session_id,
                parent_message_id=self.parent_message_id,
                ref_file_ids=ref_file_ids,
                on_tool_event=lambda event: self.call_from_thread(self.on_tool_event_progress, event),
                on_tool_approval=self.request_tool_approval,
            )
        except Exception as exc:
            log.exception("send_prompt failed")
            self.call_from_thread(self.on_reply_error, exc)
            return
        elapsed = time.perf_counter() - started_at
        self.call_from_thread(
            self.on_reply,
            turn.text or "(empty response)",
            turn.session_id,
            turn.parent_message_id,
            elapsed,
            turn.tool_events,
        )

    @work(thread=True)
    def upload_file(self, path: str) -> None:
        try:
            uploaded = self.client.upload_file(path)
            deadline = time.monotonic() + 30
            while uploaded.status not in {"SUCCESS", "FAILED"} and time.monotonic() < deadline:
                time.sleep(1)
                uploaded = self.client.fetch_file(uploaded.id)
            if uploaded.status != "SUCCESS":
                raise RuntimeError(f"File upload did not finish successfully: status={uploaded.status}")
        except Exception as exc:
            log.exception("upload_file failed")
            self.call_from_thread(self.on_upload_error, exc)
            return
        self.call_from_thread(self.on_upload_done, uploaded)

    def on_upload_done(self, uploaded: UploadedFile) -> None:
        self.attached_files.append(uploaded)
        self.busy = False
        self.stop_loader()
        self.update_status("Ready")
        self.update_stats()
        token_text = f", tokens={uploaded.token_usage}" if uploaded.token_usage is not None else ""
        self.write_system(f"Attached {uploaded.file_name} ({uploaded.file_size} bytes{token_text}).")

    def on_upload_error(self, exc: Exception) -> None:
        self.stop_loader()
        self.busy = False
        self.update_status("Upload failed")
        self.write_error(str(exc))
        self.write_system(f"Log: {self.log_file}")

    def on_reply(
        self,
        text: str,
        session_id: str,
        parent_message_id: str | int | None,
        elapsed: float,
        tool_events: list[dict[str, Any]],
    ) -> None:
        self.session_id = session_id
        self.parent_message_id = parent_message_id
        self.stream_reply(text, elapsed, tool_events)

    @work
    async def stream_reply(self, text: str, elapsed: float, tool_events: list[dict[str, Any]] | None = None) -> None:
        shown = ""
        self.set_assistant_role_loading(False)
        for chunk in self.chunk_text(text):
            shown += chunk
            widget = self.current_stream_widget
            if widget is not None:
                widget.update(shown)
                self.schedule_scroll_end()
            await asyncio.sleep(0.018)
        self.current_stream_widget = None
        self.current_stream_role = None
        self.chat_messages.append({"role": "assistant", "text": text})
        if tool_events:
            self.tool_activity_events = tool_events
            self.update_tool_activity()
        self.write_metrics(text, elapsed)
        self.schedule_scroll_end(force=True)
        self.persist_chat_session(text)
        self.busy = False
        self.stop_loader()
        self.update_status("Ready")

    def on_reply_error(self, exc: Exception) -> None:
        self.stop_loader()
        self.current_stream_widget = None
        self.set_assistant_role_loading(False)
        self.current_stream_role = None
        self.write_error(str(exc))
        self.write_system(f"Log: {self.log_file}")
        self.busy = False
        self.update_status("Request failed")

    def action_clear_chat(self) -> None:
        self.query_one("#chat", VerticalScroll).remove_children()
        self.reset_stats()
        self.write_system("Chat cleared.")

    def write_user(self, text: str) -> None:
        self.add_message("you", text, "user-role")

    def create_assistant_stream(self) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        self.current_stream_role = Static(self.role_label("deepseek"), classes="role assistant-role")
        self.current_stream_widget = Markdown("", classes="bubble")
        chat.mount(self.current_stream_role)
        chat.mount(self.current_stream_widget)
        self.schedule_scroll_end()

    def write_system(self, text: str) -> None:
        self.add_message("system", text, "system-role")

    def write_error(self, text: str) -> None:
        self.add_message("error", text, "error-role")

    def write_tool_events(self, events: list[dict[str, Any]]) -> None:
        self.tool_activity_events = events
        self.update_tool_activity()

    def on_tool_event_progress(self, event: dict[str, Any]) -> None:
        self.tool_activity_events.append(event)
        self.tool_activity_events = self.tool_activity_events[-30:]
        self.update_tool_activity()
        tool = str(event.get("tool") or "tool")
        if event.get("type") == "tool_call":
            if tool == "write_file":
                self.set_loader_prefix("Awaiting approval for write_file")
            else:
                self.set_loader_prefix(f"Running tool {tool}")
            return
        if event.get("type") == "tool_result":
            elapsed = self.format_elapsed(event.get("elapsed"))
            status = "completed" if event.get("ok") else "failed"
            self.set_loader_prefix(f"Tool {tool} {status} in {elapsed}")

    def request_tool_approval(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if tool_name != "write_file":
            return "approve_once"

        path = str(arguments.get("path") or "")
        content = str(arguments.get("content") or "")
        overwrite = bool(arguments.get("overwrite", False))
        create_dirs = bool(arguments.get("create_dirs", False))
        try:
            target = resolve_workspace_path(path)
        except Exception:
            return "deny"

        target_dir = str(target.parent)
        if target_dir in self.approved_write_dirs:
            return "approve_once"

        decision_event = threading.Event()
        decision_box: dict[str, str] = {}

        def open_dialog() -> None:
            self.push_screen(
                WriteFileApprovalScreen(
                    path=relative_workspace_path(target),
                    directory=relative_workspace_path(target.parent),
                    content=content,
                    overwrite=overwrite,
                    create_dirs=create_dirs,
                ),
                callback=lambda decision: self.on_write_file_approval(decision, target_dir, decision_box, decision_event),
            )

        self.call_from_thread(open_dialog)
        self.call_from_thread(lambda: self.set_loader_prefix(f"Approve write_file {compact_text(path or target.name, 28)}"))
        decision_event.wait()
        return decision_box.get("decision", "deny")

    def on_write_file_approval(
        self,
        decision: str | None,
        target_dir: str,
        decision_box: dict[str, str],
        decision_event: threading.Event,
    ) -> None:
        resolved = decision or "deny"
        if resolved == "approve_dir":
            self.approved_write_dirs.add(target_dir)
            resolved = "approve_once"
        decision_box["decision"] = resolved
        decision_event.set()

    def tool_event_text(self, event: dict[str, Any]) -> str:
        event_type = event.get("type")
        tool = event.get("tool", "tool")
        if event_type == "tool_call":
            return f"Tool call: {tool}"
        if event_type == "tool_result":
            status = "ok" if event.get("ok") else "failed"
            summary = event.get("summary", "")
            return f"Tool result: {tool} {status} ({summary})"
        return f"Tool event: {event_type}"

    def tool_events_text(self, events: list[dict[str, Any]]) -> str:
        lines = ["Tool activity"]
        pending_tools: list[str] = []
        for event in events:
            tool = str(event.get("tool") or "tool")
            if event.get("type") == "tool_call":
                pending_tools.append(tool)
                continue
            if event.get("type") == "tool_result":
                status = "ok" if event.get("ok") else "failed"
                summary = str(event.get("summary") or "")
                elapsed = self.format_elapsed(event.get("elapsed"))
                lines.append(f"- {tool}: {status} in {elapsed} ({summary})")
        for tool in pending_tools:
            if not any(str(event.get("tool") or "") == tool and event.get("type") == "tool_result" for event in events):
                lines.append(f"- {tool}: started")
        return "\n".join(lines)

    def format_elapsed(self, value: object) -> str:
        try:
            elapsed = float(value)
        except (TypeError, ValueError):
            return "0.00s"
        return f"{elapsed:.2f}s"

    def render_chat_history(self) -> None:
        for message in self.chat_messages:
            role = message.get("role", "")
            text = message.get("text", "")
            if role == "user":
                self.add_message("you", text, "user-role")
            elif role == "assistant":
                self.add_message("deepseek", text, "assistant-role")
            elif role == "tool":
                self.add_message("system", text, "system-role", "bubble tool-events")

    def write_attached_files(self) -> None:
        if not self.attached_files:
            self.write_system("No files attached. Use /attach /path/to/file.")
            return
        lines = [
            f"- {file.file_name} ({file.file_size} bytes, status={file.status}, id={file.id})"
            for file in self.attached_files
        ]
        self.write_system("Attached files:\n" + "\n".join(lines))

    def handle_copy_command(self, command: str) -> None:
        parts = command.split(maxsplit=1)
        target = parts[1].strip().lower() if len(parts) > 1 else "last"
        if target in {"last", "reply", "assistant"}:
            text = self.last_message_text("assistant")
            label = "last assistant reply"
        elif target == "user":
            text = self.last_message_text("user")
            label = "last user message"
        elif target in {"all", "chat", "transcript"}:
            text = self.transcript_text()
            label = "chat transcript"
        elif target in {"raw", "file"}:
            path = self.write_raw_transcript()
            self.write_system(f"Wrote raw transcript: {path}")
            return
        else:
            self.write_system("Usage: /copy, /copy last, /copy user, /copy all, or /copy raw.")
            return

        if not text:
            self.write_system(f"No {label} to copy.")
            return
        method = self.copy_text_to_clipboard(text)
        self.write_system(f"Copied {label} ({len(text)} chars) via {method}.")

    def last_message_text(self, role: str) -> str:
        for message in reversed(self.chat_messages):
            if message.get("role") == role:
                return str(message.get("text") or "")
        return ""

    def transcript_text(self) -> str:
        lines = []
        for message in self.chat_messages:
            role = message.get("role", "")
            text = str(message.get("text") or "")
            if role and text:
                lines.append(f"{role}:\n{text}")
        return "\n\n".join(lines)

    def copy_text_to_clipboard(self, text: str) -> str:
        external_method = self.copy_to_external_clipboard(text)
        try:
            super().copy_to_clipboard(text)
        except Exception:
            log.exception("textual clipboard copy failed")
        if external_method:
            return external_method
        fallback_path = self.write_clipboard_fallback(text)
        return f"terminal clipboard; fallback file {fallback_path}"

    def copy_to_external_clipboard(self, text: str) -> str | None:
        commands = [
            ("wl-copy", ["wl-copy"]),
            ("xclip", ["xclip", "-selection", "clipboard"]),
            ("xsel", ["xsel", "--clipboard", "--input"]),
            ("pbcopy", ["pbcopy"]),
            ("termux-clipboard-set", ["termux-clipboard-set"]),
        ]
        for name, command in commands:
            if shutil.which(command[0]) is None:
                continue
            try:
                subprocess.run(command, input=text, text=True, check=True, timeout=5)
                return name
            except Exception:
                log.exception("external clipboard copy failed command=%s", name)
        return None

    def write_clipboard_fallback(self, text: str) -> str:
        output_dir = project_root() / ".logs"
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "clipboard-last.txt"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def write_raw_transcript(self) -> str:
        output_dir = project_root() / ".logs"
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        session_part = self.session_id or "new-session"
        safe_session = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in session_part)[:48]
        path = output_dir / f"chat-raw-{safe_session}-{stamp}.md"
        path.write_text(self.raw_transcript_text(), encoding="utf-8")
        return str(path)

    def raw_transcript_text(self) -> str:
        payload = {
            "profile": self.profile,
            "session_id": self.session_id,
            "parent_message_id": self.parent_message_id,
            "title": self.session_title,
            "created_at": self.session_created_at,
            "exported_at": datetime.now().isoformat(),
            "messages": self.export_messages(),
            "stats": self.session_stats_payload(),
        }
        return (
            "# DeepSeek Chat Raw Transcript\n\n"
            "```json\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}\n"
            "```\n"
        )

    def export_messages(self) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for message in self.chat_messages:
            role = str(message.get("role") or "")
            text = str(message.get("text") or "")
            if role and text:
                messages.append({"role": role, "text": text})
        return messages

    def add_message(self, role: str, text: str, role_class: str, bubble_class: str = "bubble") -> None:
        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(Static(self.role_label(role), classes=f"role {role_class}"))
        chat.mount(Markdown(text, classes=bubble_class))
        self.schedule_scroll_end()

    def write_metrics(self, text: str, elapsed: float) -> None:
        token_count = self.estimate_tokens(text)
        tokens_per_second = token_count / elapsed if elapsed > 0 else 0.0
        cost = self.estimate_cost(token_count)
        self.response_count += 1
        self.total_output_tokens += token_count
        self.total_estimated_cost += cost
        self.last_elapsed = elapsed
        self.last_output_tokens = token_count
        self.last_tokens_per_second = tokens_per_second
        self.last_estimated_cost = cost
        self.update_stats()

    def reset_stats(self) -> None:
        self.response_count = 0
        self.total_output_tokens = 0
        self.total_estimated_cost = 0.0
        self.last_elapsed = 0.0
        self.last_output_tokens = 0
        self.last_tokens_per_second = 0.0
        self.last_estimated_cost = 0.0
        self.update_stats()

    def update_stats(self) -> None:
        self.query_one("#stats-info", Static).update(self.stats_text())

    def update_tool_activity(self) -> None:
        self.query_one("#tool-activity", Static).update(self.tool_activity_text())

    def set_stats_visibility(self, width: int) -> None:
        stats = self.query_one("#stats-info", Static)
        tool_activity = self.query_one("#tool-activity", Static)
        if width < 90:
            stats.add_class("hidden")
            tool_activity.add_class("hidden")
        else:
            stats.remove_class("hidden")
            tool_activity.remove_class("hidden")

    def stats_text(self) -> str:
        separator = "───────────────────────────"
        colored_separator = f"[bold cyan]{separator}[/]"
        logo_label = f"DEEPSEEK-TUI {datetime.now().strftime('%H:%M:%S')}"
        ascii_logo = f"╭{'─' * 25}╮\n│{logo_label:^25}│\n╰{'─' * 25}╯"
        
        return (
            f"[bold cyan]{ascii_logo}[/]\n"
            "\n\n"
            "Estimated Token Statistics\n"
            f"{colored_separator}\n"
            "Last response\n"
            f"  time     {self.last_elapsed:>8.2f}s\n"
            f"  output   {self.last_output_tokens:>8}\n"
            f"  tok/s    {self.last_tokens_per_second:>8.1f}\n"
            f"  cost     ${self.last_estimated_cost:>7.6f}\n"
            f"{colored_separator}\n"
            "Session\n"
            f"  replies  {self.response_count:>8}\n"
            f"  output   {self.total_output_tokens:>8}\n"
            f"  cost     ${self.total_estimated_cost:>7.6f}\n"
            f"{colored_separator}\n"
            "Attachments\n"
            f"  files    {len(self.attached_files):>8}\n"
            f"  bytes    {self.attached_file_size():>8}\n"
            f"  tokens   {self.attached_token_usage():>8}\n"
        )

    def commands_text(self) -> str:
        separator = "───────────────────────────"
        colored_separator = f"[bold cyan]{separator}[/]"
        return (
            f"{colored_separator}\n"
            "Commands\n"
            f"{self.command_list_text()}"
        )

    def tool_activity_text(self) -> str:
        separator = "─" * 28
        colored_separator = f"[bold cyan]{separator}[/]"
        if not self.tool_activity_events:
            return f"{colored_separator}\nTool Activity\n  idle"
        lines = [f"{colored_separator}", "Tool Activity"]
        activity = self.tool_events_text(self.tool_activity_events).splitlines()[1:]
        lines.extend(f"  {line}" for line in activity[-12:])
        return "\n".join(lines)

    def update_input_info(self, value: str | None = None) -> None:
        current_value = self.query_one("#prompt", Input).value if value is None else value
        self.query_one("#input-info", Static).update(self.input_info_text(current_value))

    def input_info_text(self, value: str | None = None) -> str:
        if value and value.startswith("/"):
            matches = self.matching_commands(value)
            if matches:
                return "\n".join(f"{command} {description}" for command, description in matches[:4])
            return "No matching command"
        return f"{self.model_label()}"

    def command_list_text(self) -> str:
        return "\n".join(f"  {command:<14} {description}" for command, description in self.matching_commands("/"))

    def matching_commands(self, prefix: str) -> list[tuple[str, str]]:
        normalized = prefix.strip().lower()
        matches = [
            (command, description)
            for command, description in sorted(COMMANDS, key=lambda item: item[0])
            if command.startswith(normalized)
        ]
        if normalized and " " not in normalized:
            matches.extend(
                (command, description)
                for command, description in sorted(COMMANDS, key=lambda item: item[0])
                if command.split(maxsplit=1)[0].startswith(normalized) and (command, description) not in matches
            )
        return matches

    def attached_file_size(self) -> int:
        return sum(file.file_size for file in self.attached_files)

    def attached_token_usage(self) -> int:
        return sum(file.token_usage or 0 for file in self.attached_files)

    def estimate_tokens(self, text: str) -> int:
        compact_len = len(text.strip())
        if compact_len == 0:
            return 0
        return max(1, round(compact_len / ESTIMATED_CHARS_PER_TOKEN))

    def estimate_cost(self, output_tokens: int) -> float:
        raw_rate = os.getenv("DEEPSEEK_ESTIMATED_OUTPUT_COST_PER_1M_TOKENS_USD")
        try:
            rate = float(raw_rate) if raw_rate is not None else DEFAULT_OUTPUT_COST_PER_1M_TOKENS_USD
        except ValueError:
            rate = DEFAULT_OUTPUT_COST_PER_1M_TOKENS_USD
        return output_tokens / 1_000_000 * rate

    def role_label(self, role: str) -> str:
        icon = ROLE_ICONS.get(role, "•")
        return f"{icon} {role}"

    def start_loader(self, prefix: str) -> None:
        self.loading = True
        self.loading_prefix = prefix
        self.loading_frame = 0
        self.set_assistant_role_loading(True)
        self.update_loader()
        self.run_loader()

    def stop_loader(self) -> None:
        self.loading = False
        self.set_assistant_role_loading(False)

    def set_loader_prefix(self, prefix: str) -> None:
        self.loading_prefix = prefix
        if self.loading:
            self.update_loader()

    @work
    async def run_loader(self) -> None:
        while self.loading:
            self.update_loader()
            await asyncio.sleep(0.09)

    def update_loader(self) -> None:
        frame = SPINNER_FRAMES[self.loading_frame % len(SPINNER_FRAMES)]
        self.loading_frame += 1
        self.set_assistant_role_loading(True, frame)

    def set_assistant_role_loading(self, loading: bool, frame: str | None = None) -> None:
        if self.current_stream_role is None:
            return
        suffix = f" {frame}" if loading and frame else ""
        detail = f" {self.loading_prefix}" if loading and self.loading_prefix else ""
        self.current_stream_role.update(f"{self.role_label('deepseek')}{detail}{suffix}")

    def scroll_chat_end(self) -> None:
        self.query_one("#chat", VerticalScroll).scroll_end(animate=False)
        self.scroll_pending = False

    def schedule_scroll_end(self, force: bool = False) -> None:
        if self.scroll_pending and not force:
            return
        self.scroll_pending = True
        self.call_after_refresh(self.scroll_chat_end)
        self.set_timer(0.05, self.scroll_chat_end)
        if force:
            self.set_timer(0.15, self.scroll_chat_end)
            self.set_timer(0.35, self.scroll_chat_end)

    def chunk_text(self, text: str) -> list[str]:
        chunks: list[str] = []
        index = 0
        chunk_size = 24
        if len(text) > 40000:
            chunk_size = 1024
        elif len(text) > 12000:
            chunk_size = 512
        elif len(text) > 4000:
            chunk_size = 192
        elif len(text) > 1200:
            chunk_size = 96
        elif len(text) > 400:
            chunk_size = 48
        while index < len(text):
            chunks.append(text[index : index + chunk_size])
            index += chunk_size
        return chunks or [text]

    def model_label(self) -> str:
        thinking = "on" if self.client.thinking_enabled else "off"
        return f"profile={self.profile} model_type={self.client.model_type} thinking={thinking}"

    def update_status(self, _prefix: str) -> None:
        self.sub_title = self.model_label()
        self.update_input_info()

    def persist_chat_session(self, assistant_text: str) -> None:
        if not self.session_id:
            return
        now = datetime.now().isoformat()
        if not self.session_created_at:
            self.session_created_at = now
        if not self.session_title:
            self.session_title = compact_text(self.pending_prompt or assistant_text, 52)
        self.session_preview = compact_text(assistant_text, 72)
        self.turn_count += 1
        try:
            save_chat_session(
                profile=self.profile,
                chat_session_id=self.session_id,
                parent_message_id=self.parent_message_id,
                title=self.session_title,
                preview=self.session_preview,
                turn_count=self.turn_count,
                created_at=self.session_created_at,
                updated_at=now,
                messages=self.chat_messages,
                stats=self.session_stats_payload(),
            )
        except Exception:
            log.exception("failed to persist chat session")
            self.write_system("Could not save chat session state.")
        self.title = f"deepseek-chat-python - {compact_text(self.session_label(), 24)}"

    def session_label(self) -> str:
        return self.session_title or self.session_id or "new session"

    def session_stats_payload(self) -> dict[str, float | int]:
        return {
            "response_count": self.response_count,
            "total_output_tokens": self.total_output_tokens,
            "total_estimated_cost": self.total_estimated_cost,
            "last_elapsed": self.last_elapsed,
            "last_output_tokens": self.last_output_tokens,
            "last_tokens_per_second": self.last_tokens_per_second,
            "last_estimated_cost": self.last_estimated_cost,
        }

    def handle_model_command(self, command: str) -> None:
        parts = command.split(maxsplit=1)
        if len(parts) == 1:
            current = self.client.model_type if self.client.model_type in MODEL_TYPES else "default"
            current_index = MODEL_TYPES.index(current)
            self.client.model_type = MODEL_TYPES[(current_index + 1) % len(MODEL_TYPES)]
            self.write_system(f"Switched model_type to {self.client.model_type}. {self.model_label()}.")
            self.update_status("Ready")
            return

        requested = parts[1].strip().lower()
        if requested in MODEL_TYPES:
            self.client.model_type = requested
            label = requested
        else:
            self.write_system("Unknown model_type. Use /model default or /model expert.")
            self.update_status("Ready")
            return

        self.write_system(f"Switched model_type to {label}. {self.model_label()}.")
        self.update_status("Ready")


def main() -> None:
    log_file = setup_logging()
    load_dotenv(project_root() / ".env")
    parser = argparse.ArgumentParser(description="DeepSeek web chat Textual TUI")
    parser.add_argument("--profile", default="default", help="SQLite auth profile. Defaults to default.")
    parser.add_argument("mode", nargs="?", choices=["resume"], help="Resume a saved chat session.")
    args = parser.parse_args()
    try:
        if args.mode == "resume":
            sessions = list_chat_sessions(args.profile)
            if not sessions:
                print(f"No saved chat sessions for profile={args.profile}")
                return
            selected = ChatSessionPicker(profile=args.profile).run()
            if selected is None:
                return
            DeepSeekTui(profile=args.profile, resume_session=selected).run()
            return
        DeepSeekTui(profile=args.profile).run()
    except Exception:
        get_logger("tui").exception("tui crashed")
        print(f"log: {log_file}")
        raise


if __name__ == "__main__":
    main()
