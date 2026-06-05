from __future__ import annotations

import argparse
import asyncio
import os
import shlex
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Label, ListItem, ListView, Markdown, Static

from .client import DeepSeekClient, UploadedFile
from .logging_config import get_logger, setup_logging
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
COMMANDS = [
    ("/attach", "upload file"),
    ("/clear-files", "clear files"),
    ("/exit", "quit"),
    ("/files", "list files"),
    ("/model", "toggle model"),
    ("/model default", "default model"),
    ("/model expert", "expert model"),
    ("/q", "quit"),
    ("/quit", "quit"),
]

welcome = f"""⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡀⠀⠀⠀⠀⠀⠀⢀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
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
[bold cyan]                             ╭{'─' * 25}╮  
[bold cyan]    ▓█████▄ ▓█████ ▓█████  ██▓███    ██████ ▓█████ ▓█████  ██ ▄█▀
[bold cyan]    ▒██▀ ██▌▓█   ▀ ▓█   ▀ ▓██░  ██▒▒██    ▒ ▓█   ▀ ▓█   ▀  ██▄█▒
[bold cyan]    ░██   █▌▒███   ▒███   ▓██░ ██▓▒░ ▓██▄   ▒███   ▒███   ▓███▄░
[bold cyan]    ░▓█▄   ▌▒▓█  ▄ ▒▓█  ▄ ▒██▄█▓▒ ▒  ▒   ██▒▒▓█  ▄ ▒▓█  ▄ ▓██ █▄
[bold cyan]    ░▒████▓ ░▒████▒░▒████▒▒██▒ ░  ░▒██████▒▒░▒████▒░▒████▒▒██▒ █▄
[bold cyan]    ╚═══▀  ░░ ▒░ ░░░ ▒░ ░▒▓▒░ ░  ░▒ ▒▓▒ ▒ ░░░ ▒░ ░░░ ▒░ ░▒ ▒▒ ▓▒
[bold cyan]            ╰{'─' * 30}╯
"""


def compact_text(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "…"


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
        border: none;
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

    def compose(self) -> ComposeResult:
        with Horizontal(id="workspace"):
            yield VerticalScroll(id="chat")
            with Vertical(id="stats"):
                yield Static(self.stats_text(), id="stats-info")
                yield Static("", classes="spacing")                # Pendorong Tengah (1fr)
                yield Static(self.commands_text(), id="stats-cmds")
        with Vertical(id="composer"):
            yield Input(placeholder="Type message, /attach path, /files, /model, /quit", id="prompt")
            yield Static(self.input_info_text(), id="input-info")

    def on_mount(self) -> None:
        log.info("tui mounted profile=%s", self.profile)
        self.title = "deepseek-chat-python"
        self.sub_title = self.model_label()
        if self.session_record:
            self.title = f"deepseek-chat-python - {compact_text(self.session_label(), 24)}"
        self.query_one("#prompt", Input).focus()
        self.set_interval(1, self.update_input_info)
        self.set_interval(1, self.update_stats)
        self.set_stats_visibility(self.size.width)
        if self.session_record:
            self.render_chat_history()
            self.write_system(f"Resumed session: {self.session_label()}")
        ascii_art = Static(welcome, markup=True, classes="bubble")
        self.query_one("#chat", VerticalScroll).mount(ascii_art)
        self.write_system("Type a message and press Enter. Use /model to switch model_type.")

    def on_click(self) -> None:
        self.query_one("#prompt", Input).focus()

    def on_resize(self, event: object) -> None:
        size = getattr(event, "size", None)
        width = getattr(size, "width", self.size.width)
        self.set_stats_visibility(width)

    def on_unmount(self) -> None:
        log.info("tui unmount")
        self.client.close()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        prompt = event.value.strip()
        event.input.value = ""
        if not prompt:
            return
        if prompt in {"/q", "/quit", "/exit"}:
            self.exit()
            return
        if prompt == "/files":
            self.write_attached_files()
            return
        if prompt == "/clear-files":
            self.attached_files.clear()
            self.update_stats()
            self.write_system("Cleared attached files.")
            return
        if prompt.startswith("/attach "):
            if self.busy:
                self.write_system("Request is still running. Wait for the current reply first.")
                return
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
            log.info("model command=%s", prompt)
            self.handle_model_command(prompt)
            return
        if self.busy:
            self.write_system("Request is still running. Wait for the current reply first.")
            return

        self.write_user(prompt)
        self.chat_messages.append({"role": "user", "text": prompt})
        self.pending_prompt = prompt
        self.busy = True
        self.create_assistant_stream()
        self.start_loader("DeepSeek is replying")
        log.info("submitting prompt len=%s", len(prompt))
        self.send_prompt(prompt, [file.id for file in self.attached_files])

    def on_input_changed(self, event: Input.Changed) -> None:
        self.update_input_info(event.value)

    @work(thread=True)
    def send_prompt(self, prompt: str, ref_file_ids: list[str]) -> None:
        started_at = time.perf_counter()
        try:
            turn = self.client.chat(
                prompt,
                session_id=self.session_id,
                parent_message_id=self.parent_message_id,
                ref_file_ids=ref_file_ids,
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

    def on_reply(self, text: str, session_id: str, parent_message_id: str | int | None, elapsed: float) -> None:
        self.session_id = session_id
        self.parent_message_id = parent_message_id
        self.stream_reply(text, elapsed)

    @work
    async def stream_reply(self, text: str, elapsed: float) -> None:
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

    def render_chat_history(self) -> None:
        for message in self.chat_messages:
            role = message.get("role", "")
            text = message.get("text", "")
            if role == "user":
                self.add_message("you", text, "user-role")
            elif role == "assistant":
                self.add_message("deepseek", text, "assistant-role")

    def write_attached_files(self) -> None:
        if not self.attached_files:
            self.write_system("No files attached. Use /attach /path/to/file.")
            return
        lines = [
            f"- {file.file_name} ({file.file_size} bytes, status={file.status}, id={file.id})"
            for file in self.attached_files
        ]
        self.write_system("Attached files:\n" + "\n".join(lines))

    def add_message(self, role: str, text: str, role_class: str) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(Static(self.role_label(role), classes=f"role {role_class}"))
        chat.mount(Markdown(text, classes="bubble"))
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

    def set_stats_visibility(self, width: int) -> None:
        stats = self.query_one("#stats-info", Static)
        if width < 90:
            stats.add_class("hidden")
        else:
            stats.remove_class("hidden")

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
        self.current_stream_role.update(f"{self.role_label('deepseek')}{suffix}")

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
    load_dotenv()
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
