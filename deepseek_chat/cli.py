from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .logging_config import get_logger, project_root, setup_logging
from .session_store import load_session


def print_status(profile: str, as_json: bool = False) -> None:
    session = load_session(profile)
    if not session:
        payload = {
            "profile": profile,
            "status": "not logged in",
            "session": "no stored auth session found",
        }
        if as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        print(f"profile: {profile}")
        print("status: not logged in")
        print("session: no stored auth session found")
        return

    logged_in = bool(session.bearer and session.cookie_header)
    payload = {
        "profile": profile,
        "status": "logged in" if logged_in else "session incomplete",
        "captured_at": session.captured_at,
        "bearer": "present" if session.bearer else "missing",
        "cookie_header": "present" if session.cookie_header else "missing",
        "ds_session_id": "present" if session.ds_session_id else "missing",
        "x_hif_leim": "present" if session.x_hif_leim else "missing",
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"profile: {profile}")
    print(f"status: {payload['status']}")
    print(f"captured_at: {payload['captured_at']}")
    print(f"bearer: {payload['bearer']}")
    print(f"cookie_header: {payload['cookie_header']}")
    print(f"ds_session_id: {payload['ds_session_id']}")
    print(f"x_hif_leim: {payload['x_hif_leim']}")


def load_environment() -> None:
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        return
    load_dotenv(Path.cwd() / ".env")
    load_dotenv(project_root() / ".env")


def prompt_tool_approval(tool_name: str, arguments: dict[str, object]) -> str:
    if not sys.stdin.isatty():
        return "deny"

    if tool_name == "run_command":
        command = arguments.get("command", "")
        display_command = shlex.join(command) if isinstance(command, list) else str(command)
        cwd = str(arguments.get("cwd") or ".")
        print(f"\nTool approval needed: run_command")
        print(f"  command: {display_command}")
        print(f"  cwd: {cwd}")
    elif tool_name == "write_file":
        print(f"\nTool approval needed: write_file")
        print(f"  path: {arguments.get('path', '')}")
        print(f"  overwrite: {bool(arguments.get('overwrite', False))}")
        print(f"  create_dirs: {bool(arguments.get('create_dirs', False))}")
    else:
        print(f"\nTool approval needed: {tool_name}")

    try:
        answer = input("Approve? [y/N]: ").strip().lower()
    except EOFError:
        return "deny"
    return "approve_once" if answer in {"y", "yes"} else "deny"


def main() -> None:
    log_file = setup_logging()
    log = get_logger("cli")

    parser = argparse.ArgumentParser(description="Minimal DeepSeek web chat CLI")
    parser.add_argument("--profile", default="default", help="SQLite auth profile. Defaults to default.")
    subparsers = parser.add_subparsers(dest="command")
    status_parser = subparsers.add_parser("status", help="Show whether the active profile is logged in.")
    status_parser.add_argument("--json", action="store_true", help="Print status as JSON.")
    parser.add_argument("prompt", nargs="*", help="Prompt text. Omit for interactive mode.")
    args = parser.parse_args()

    if args.command == "status":
        if args.prompt:
            parser.error("status does not take a prompt")
        print_status(args.profile, as_json=args.json)
        return

    load_environment()
    from .client import DeepSeekClient

    client = DeepSeekClient(profile=args.profile)
    session_id: str | None = None
    parent_message_id: str | int | None = None

    try:
        if args.prompt:
            turn = client.chat_with_tools(" ".join(args.prompt), on_tool_approval=prompt_tool_approval)
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
            turn = client.chat_with_tools(
                prompt,
                session_id=session_id,
                parent_message_id=parent_message_id,
                on_tool_approval=prompt_tool_approval,
            )
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
