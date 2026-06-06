from __future__ import annotations

import argparse
import sys

from .logging_config import get_logger, project_root, setup_logging
from .session_store import load_session


def print_status(profile: str) -> None:
    session = load_session(profile)
    print(f"profile: {profile}")
    if not session:
        print("status: not logged in")
        print("session: no stored auth session found")
        return

    logged_in = bool(session.bearer and session.cookie_header)
    print(f"status: {'logged in' if logged_in else 'session incomplete'}")
    print(f"captured_at: {session.captured_at}")
    print(f"bearer: {'present' if session.bearer else 'missing'}")
    print(f"cookie_header: {'present' if session.cookie_header else 'missing'}")
    print(f"ds_session_id: {'present' if session.ds_session_id else 'missing'}")
    print(f"x_hif_leim: {'present' if session.x_hif_leim else 'missing'}")


def load_environment() -> None:
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        return
    load_dotenv(project_root() / ".env")


def main() -> None:
    log_file = setup_logging()
    log = get_logger("cli")

    parser = argparse.ArgumentParser(description="Minimal DeepSeek web chat CLI")
    parser.add_argument("--profile", default="default", help="SQLite auth profile. Defaults to default.")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status", help="Show whether the active profile is logged in.")
    parser.add_argument("prompt", nargs="*", help="Prompt text. Omit for interactive mode.")
    args = parser.parse_args()

    if args.command == "status":
        if args.prompt:
            parser.error("status does not take a prompt")
        print_status(args.profile)
        return

    load_environment()
    from .client import DeepSeekClient

    client = DeepSeekClient(profile=args.profile)
    session_id: str | None = None
    parent_message_id: str | int | None = None

    try:
        if args.prompt:
            turn = client.chat_with_tools(" ".join(args.prompt))
            print(turn.text)
            return

        print("DeepSeek chat. Ctrl-D / Ctrl-C to exit.")
        while True:
            try:
                prompt = input("> ").strip()
            except EOFError:
                print()
                return
            if not prompt:
                continue
            turn = client.chat_with_tools(prompt, session_id=session_id, parent_message_id=parent_message_id)
            session_id = turn.session_id
            parent_message_id = turn.parent_message_id
            print(turn.text)
    except KeyboardInterrupt:
        print()
    except Exception as exc:
        log.exception("cli failed")
        print(f"error: {exc}", file=sys.stderr)
        print(f"log: {log_file}", file=sys.stderr)
        raise SystemExit(1)
    finally:
        client.close()


if __name__ == "__main__":
    main()
