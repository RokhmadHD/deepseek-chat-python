from __future__ import annotations

import curses
import textwrap
from dataclasses import dataclass

from dotenv import load_dotenv

from .client import DeepSeekClient


@dataclass
class Message:
    role: str
    text: str


class ChatTui:
    def __init__(self, screen: curses.window) -> None:
        self.screen = screen
        self.client = DeepSeekClient()
        self.messages: list[Message] = []
        self.input_text = ""
        self.session_id: str | None = None
        self.parent_message_id: str | None = None
        self.scroll = 0
        self.status = "Enter: send | /quit: exit | PgUp/PgDn: scroll"

    def close(self) -> None:
        self.client.close()

    def run(self) -> None:
        curses.curs_set(1)
        self.screen.keypad(True)
        self.screen.timeout(-1)
        self.draw()

        while True:
            key = self.screen.getch()
            if key in (curses.KEY_RESIZE,):
                self.draw()
            elif key in (curses.KEY_PPAGE,):
                self.scroll += 5
                self.draw()
            elif key in (curses.KEY_NPAGE,):
                self.scroll = max(0, self.scroll - 5)
                self.draw()
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                self.input_text = self.input_text[:-1]
                self.draw()
            elif key in (10, 13):
                if not self.submit():
                    return
            elif 0 <= key <= 255:
                ch = chr(key)
                if ch == "\x03":
                    return
                if ch.isprintable():
                    self.input_text += ch
                    self.draw()

    def submit(self) -> bool:
        prompt = self.input_text.strip()
        self.input_text = ""
        if not prompt:
            self.draw()
            return True
        if prompt in {"/q", "/quit", "/exit"}:
            return False

        self.messages.append(Message("you", prompt))
        self.status = "DeepSeek is replying..."
        self.scroll = 0
        self.draw()

        try:
            turn = self.client.chat(prompt, session_id=self.session_id, parent_message_id=self.parent_message_id)
            self.session_id = turn.session_id
            self.parent_message_id = turn.parent_message_id
            self.messages.append(Message("deepseek", turn.text or "(empty response)"))
            self.status = f"session: {self.session_id} | Enter: send | /quit: exit"
        except Exception as exc:
            self.messages.append(Message("error", str(exc)))
            self.status = "request failed | Enter: send | /quit: exit"

        self.draw()
        return True

    def draw(self) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        if height < 8 or width < 30:
            self.screen.addstr(0, 0, "Terminal too small")
            self.screen.refresh()
            return

        chat_height = height - 4
        self.draw_header(width)
        self.draw_messages(1, chat_height, width)
        self.draw_input(height - 3, width)
        self.screen.refresh()

    def draw_header(self, width: int) -> None:
        title = " deepseek-chat-python "
        self.screen.addstr(0, 0, title[:width], curses.A_REVERSE)
        if len(title) < width:
            self.screen.addstr(0, len(title), " " * (width - len(title)), curses.A_REVERSE)

    def draw_messages(self, start_y: int, chat_height: int, width: int) -> None:
        lines = self.render_message_lines(width)
        visible = lines[max(0, len(lines) - chat_height - self.scroll) : len(lines) - self.scroll if self.scroll else len(lines)]
        for idx, line in enumerate(visible[:chat_height]):
            attr = curses.A_NORMAL
            if line.startswith("you:"):
                attr = curses.A_BOLD
            elif line.startswith("error:"):
                attr = curses.A_REVERSE
            self.screen.addstr(start_y + idx, 0, line[: width - 1], attr)

    def render_message_lines(self, width: int) -> list[str]:
        if not self.messages:
            return ["Type a message below. Use /quit to exit."]

        lines: list[str] = []
        wrap_width = max(20, width - 4)
        for message in self.messages:
            prefix = f"{message.role}: "
            wrapped = textwrap.wrap(message.text, width=wrap_width, replace_whitespace=False) or [""]
            lines.append((prefix + wrapped[0])[: width - 1])
            indent = " " * len(prefix)
            for line in wrapped[1:]:
                lines.append((indent + line)[: width - 1])
            lines.append("")
        return lines

    def draw_input(self, y: int, width: int) -> None:
        separator = "-" * width
        self.screen.addstr(y, 0, separator[:width])
        self.screen.addstr(y + 1, 0, self.status[: width - 1])
        prompt = "> " + self.input_text
        self.screen.addstr(y + 2, 0, prompt[-(width - 1) :])
        cursor_x = min(width - 1, len(prompt))
        self.screen.move(y + 2, cursor_x)


def _run(screen: curses.window) -> None:
    app = ChatTui(screen)
    try:
        app.run()
    finally:
        app.close()


def main() -> None:
    load_dotenv()
    curses.wrapper(_run)
