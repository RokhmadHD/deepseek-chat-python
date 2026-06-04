from __future__ import annotations

import argparse
import asyncio

from dotenv import load_dotenv
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Header, Input, Label, Markdown, Static

from .client import DeepSeekClient
from .logging_config import get_logger, setup_logging

log = get_logger("tui")


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
        self.current_stream_widget: Markdown | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self.status_text(), id="status")
        yield VerticalScroll(id="chat")
        with Horizontal(id="composer"):
            yield Label("> ")
            yield Input(placeholder="Type message, /model, /model r1, /quit", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        log.info("tui mounted profile=%s", self.profile)
        self.title = "deepseek-chat-python"
        self.sub_title = self.model_label()
        self.query_one("#prompt", Input).focus()
        self.write_system("Type a message and press Enter. Use /model to switch mode.")

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
        self.update_status("DeepSeek is replying...")
        log.info("submitting prompt len=%s", len(prompt))
        self.send_prompt(prompt)

    @work(thread=True)
    def send_prompt(self, prompt: str) -> None:
        try:
            turn = self.client.chat(prompt, session_id=self.session_id, parent_message_id=self.parent_message_id)
        except Exception as exc:
            log.exception("send_prompt failed")
            self.call_from_thread(self.on_reply_error, exc)
            return
        self.call_from_thread(self.on_reply, turn.text or "(empty response)", turn.session_id, turn.parent_message_id)

    def on_reply(self, text: str, session_id: str, parent_message_id: str | int | None) -> None:
        self.session_id = session_id
        self.parent_message_id = parent_message_id
        self.current_stream_widget = self.create_assistant_stream()
        self.stream_reply(text)

    @work
    async def stream_reply(self, text: str) -> None:
        shown = ""
        for chunk in self.chunk_text(text):
            shown += chunk
            widget = self.current_stream_widget
            if widget is not None:
                widget.update(shown)
                self.scroll_chat_end()
            await asyncio.sleep(0.018)
        self.current_stream_widget = None
        self.busy = False
        self.update_status("Ready")

    def on_reply_error(self, exc: Exception) -> None:
        self.write_error(str(exc))
        self.write_system(f"Log: {self.log_file}")
        self.busy = False
        self.update_status("Request failed")

    def action_clear_chat(self) -> None:
        self.query_one("#chat", VerticalScroll).remove_children()
        self.write_system("Chat cleared.")

    def write_user(self, text: str) -> None:
        self.add_message("you", text, "user-role")

    def create_assistant_stream(self) -> Markdown:
        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(Static("deepseek", classes="role assistant-role"))
        widget = Markdown("", classes="bubble")
        chat.mount(widget)
        self.scroll_chat_end()
        return widget

    def write_system(self, text: str) -> None:
        self.add_message("system", text, "system-role")

    def write_error(self, text: str) -> None:
        self.add_message("error", text, "error-role")

    def add_message(self, role: str, text: str, role_class: str) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(Static(role, classes=f"role {role_class}"))
        chat.mount(Markdown(text, classes="bubble"))
        self.scroll_chat_end()

    def scroll_chat_end(self) -> None:
        self.query_one("#chat", VerticalScroll).scroll_end(animate=False)

    def chunk_text(self, text: str) -> list[str]:
        chunks: list[str] = []
        current = ""
        for part in text.split(" "):
            piece = part if not current else f" {part}"
            if len(current) + len(piece) > 18:
                if current:
                    chunks.append(current)
                current = piece.lstrip()
            else:
                current += piece
        if current:
            chunks.append(current)
        return chunks or [text]

    def model_label(self) -> str:
        mode = "reasoner" if self.client.thinking_enabled else "chat"
        return f"profile={self.profile} model={self.client.model_type} mode={mode}"

    def status_text(self, prefix: str = "Ready") -> str:
        return f"{prefix} | {self.model_label()} | /model chat | /model r1 | /quit"

    def update_status(self, prefix: str) -> None:
        self.sub_title = self.model_label()
        self.query_one("#status", Static).update(self.status_text(prefix))

    def handle_model_command(self, command: str) -> None:
        parts = command.split(maxsplit=1)
        if len(parts) == 1:
            self.write_system(
                f"{self.model_label()}. Use /model chat, /model r1, /model reasoner, or /model <model_type>."
            )
            self.update_status("Ready")
            return

        requested = parts[1].strip().lower()
        if requested in {"chat", "default", "v3"}:
            self.client.model_type = "default"
            self.client.thinking_enabled = False
            label = "chat"
        elif requested in {"r1", "reasoner", "reasoning", "think", "thinking"}:
            self.client.model_type = "default"
            self.client.thinking_enabled = True
            label = "reasoner"
        else:
            self.client.model_type = parts[1].strip()
            self.client.thinking_enabled = False
            label = self.client.model_type

        self.write_system(f"Switched model to {label}. {self.model_label()}.")
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
