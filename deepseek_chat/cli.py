from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from .client import DeepSeekClient
from .logging_config import get_logger, setup_logging


def main() -> None:
    log_file = setup_logging()
    log = get_logger("cli")
    load_dotenv()

    parser = argparse.ArgumentParser(description="Minimal DeepSeek web chat CLI")
    parser.add_argument("--profile", default="default", help="SQLite auth profile. Defaults to default.")
    parser.add_argument("prompt", nargs="*", help="Prompt text. Omit for interactive mode.")
    args = parser.parse_args()

    client = DeepSeekClient(profile=args.profile)
    session_id: str | None = None
    parent_message_id: str | None = None

    try:
        if args.prompt:
            turn = client.chat(" ".join(args.prompt))
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
            turn = client.chat(prompt, session_id=session_id, parent_message_id=parent_message_id)
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
