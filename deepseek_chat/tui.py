from __future__ import annotations

import argparse
import asyncio
import os
import time

from dotenv import load_dotenv
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Header, Input, Label, Markdown, Static

from .client import DeepSeekClient
from .logging_config import get_logger, setup_logging

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


class DeepSeekTui(App[None]):
    CSS = """
    Screen {
        layout: vertical;
    }

    #status {
        height: 1;
        padding: 0 1;
        background: $panel;
        color: $text;
    }

    #chat {
        height: 1fr;
        border: solid $primary;
        padding: 0 1;
    }

    #composer {
        height: 3;
        padding: 0 1;
        background: $surface;
    }

    #prompt {
        width: 1fr;
    }

    .role {
        text-style: bold;
        margin-top: 1;
    }

    .user-role {
        color: cyan;
    }

    .assistant-role {
        color: green;
    }

    .system-role {
        color: $text-muted;
    }

    .error-role {
        color: red;
    }

    .bubble {
        margin-bottom: 1;
    }

    .metrics {
        color: $text-muted;
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear_chat", "Clear"),
    ]

    def __init__(self, profile: str = "default") -> None:
        super().__init__()
        self.log_file = setup_logging()
        self.profile = profile
        self.client = DeepSeekClient(profile=profile)
        self.session_id: str | None = None
        self.parent_message_id: str | int | None = None
        self.busy = False
        self.loading = False
        self.loading_frame = 0
        self.loading_prefix = "DeepSeek is replying"
        self.current_stream_role: Static | None = None
        self.current_stream_widget: Markdown | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self.status_text(), id="status")
        yield VerticalScroll(id="chat")
        with Horizontal(id="composer"):
            yield Label("> ")
            yield Input(placeholder="Type message, /model, /model expert, /quit", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        log.info("tui mounted profile=%s", self.profile)
        self.title = "deepseek-chat-python"
        self.sub_title = self.model_label()
        self.query_one("#prompt", Input).focus()
        self.write_system("Type a message and press Enter. Use /model to switch model_type.")

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
        if prompt == "/model" or prompt.startswith("/model "):
            log.info("model command=%s", prompt)
            self.handle_model_command(prompt)
            return
        if self.busy:
            self.write_system("Request is still running. Wait for the current reply first.")
            return

        self.write_user(prompt)
        self.busy = True
        self.create_assistant_stream()
        self.start_loader("DeepSeek is replying")
        log.info("submitting prompt len=%s", len(prompt))
        self.send_prompt(prompt)

    @work(thread=True)
    def send_prompt(self, prompt: str) -> None:
        started_at = time.perf_counter()
        try:
            turn = self.client.chat(prompt, session_id=self.session_id, parent_message_id=self.parent_message_id)
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
                self.scroll_chat_end()
            await asyncio.sleep(0.018)
        self.current_stream_widget = None
        self.current_stream_role = None
        self.write_metrics(text, elapsed)
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
        self.write_system("Chat cleared.")

    def write_user(self, text: str) -> None:
        self.add_message("you", text, "user-role")

    def create_assistant_stream(self) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        self.current_stream_role = Static(self.role_label("deepseek"), classes="role assistant-role")
        self.current_stream_widget = Markdown("", classes="bubble")
        chat.mount(self.current_stream_role)
        chat.mount(self.current_stream_widget)
        self.scroll_chat_end()

    def write_system(self, text: str) -> None:
        self.add_message("system", text, "system-role")

    def write_error(self, text: str) -> None:
        self.add_message("error", text, "error-role")

    def add_message(self, role: str, text: str, role_class: str) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(Static(self.role_label(role), classes=f"role {role_class}"))
        chat.mount(Markdown(text, classes="bubble"))
        self.scroll_chat_end()

    def write_metrics(self, text: str, elapsed: float) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        token_count = self.estimate_tokens(text)
        tokens_per_second = token_count / elapsed if elapsed > 0 else 0.0
        cost = self.estimate_cost(token_count)
        chat.mount(
            Static(
                (
                    f"      time {elapsed:>6.2f}s"
                    f"   tokens {token_count:>5}"
                    f"   tok/s {tokens_per_second:>6.1f}"
                    f"   cost ${cost:>8.6f}"
                ),
                classes="metrics",
            )
        )
        self.scroll_chat_end()

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
        self.query_one("#status", Static).update(self.status_text(f"{frame} {self.loading_prefix}"))
        self.set_assistant_role_loading(True, frame)

    def set_assistant_role_loading(self, loading: bool, frame: str | None = None) -> None:
        if self.current_stream_role is None:
            return
        suffix = f" {frame}" if loading and frame else ""
        self.current_stream_role.update(f"{self.role_label('deepseek')}{suffix}")

    def scroll_chat_end(self) -> None:
        self.query_one("#chat", VerticalScroll).scroll_end(animate=False)

    def chunk_text(self, text: str) -> list[str]:
        chunks: list[str] = []
        index = 0
        while index < len(text):
            chunks.append(text[index : index + 12])
            index += 12
        return chunks or [text]

    def model_label(self) -> str:
        thinking = "on" if self.client.thinking_enabled else "off"
        return f"profile={self.profile} model_type={self.client.model_type} thinking={thinking}"

    def status_text(self, prefix: str = "Ready") -> str:
        return f"{prefix} | {self.model_label()} | /model default | /model expert | /quit"

    def update_status(self, prefix: str) -> None:
        self.sub_title = self.model_label()
        self.query_one("#status", Static).update(self.status_text(prefix))

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
    args = parser.parse_args()
    try:
        DeepSeekTui(profile=args.profile).run()
    except Exception:
        get_logger("tui").exception("tui crashed")
        print(f"log: {log_file}")
        raise


if __name__ == "__main__":
    main()
