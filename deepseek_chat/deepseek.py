from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="deepseek", description="DeepSeek command wrapper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    tui_parser = subparsers.add_parser("tui", help="Open the TUI client.")
    tui_parser.add_argument("--profile", default="default", help="SQLite auth profile. Defaults to default.")
    tui_parser.add_argument("mode", nargs="?", choices=["resume"], help="Resume a saved chat session.")

    login_parser = subparsers.add_parser("login", help="Capture and save a login session.")
    login_parser.add_argument("--url", default=None, help="DeepSeek start URL.")
    login_parser.add_argument("--output-dir", default=None, help="Capture output dir.")
    login_parser.add_argument("--browser-path", default=None, help="Browser executable path.")
    login_parser.add_argument("--headless", action="store_true", help="Run browser headless.")
    login_parser.add_argument("--manual", action="store_true", help="Wait for Enter before saving.")
    login_parser.add_argument("--wait-timeout", type=int, default=None, help="Seconds to wait for login auto-detection.")
    login_parser.add_argument("--profile", default="default", help="SQLite auth profile to replace. Defaults to default.")
    login_parser.add_argument("--no-db", action="store_true", help="Save capture only; do not update SQLite.")

    status_parser = subparsers.add_parser("status", help="Show whether the active profile is logged in.")
    status_parser.add_argument("--profile", default="default", help="SQLite auth profile. Defaults to default.")
    status_parser.add_argument("--json", action="store_true", help="Print status as JSON.")

    reinstall_parser = subparsers.add_parser("reinstall", help="Reinstall the current project into the active environment.")
    reinstall_parser.add_argument(
        "--path",
        default=".",
        help="Project path to reinstall from. Defaults to the current working directory.",
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    handlers: dict[str, Callable[[argparse.Namespace], None]] = {
        "tui": _run_tui,
        "login": _run_login,
        "reinstall": _run_reinstall,
        "status": _run_status,
    }
    handler = handlers[args.command]
    handler(args)


def _run_tui(args: argparse.Namespace) -> None:
    from .tui import main as tui_main

    forwarded = ["--profile", args.profile]
    if args.mode:
        forwarded.append(args.mode)
    tui_main(forwarded)


def _run_login(args: argparse.Namespace) -> None:
    from .login import main as login_main

    forwarded = ["--profile", args.profile]
    if args.url is not None:
        forwarded.extend(["--url", args.url])
    if args.output_dir is not None:
        forwarded.extend(["--output-dir", args.output_dir])
    if args.browser_path is not None:
        forwarded.extend(["--browser-path", args.browser_path])
    if args.headless:
        forwarded.append("--headless")
    if args.manual:
        forwarded.append("--manual")
    if args.wait_timeout is not None:
        forwarded.extend(["--wait-timeout", str(args.wait_timeout)])
    if args.no_db:
        forwarded.append("--no-db")
    login_main(forwarded)


def _run_status(args: argparse.Namespace) -> None:
    from .cli import print_status

    print_status(args.profile, as_json=args.json)


def _run_reinstall(args: argparse.Namespace) -> None:
    project_path = Path(args.path).expanduser().resolve()
    if not project_path.exists():
        raise SystemExit(f"project path does not exist: {project_path}")
    if not (project_path / "pyproject.toml").exists():
        raise SystemExit(f"pyproject.toml not found: {project_path}")

    pipx = shutil.which("pipx")
    if pipx:
        command = [pipx, "install", "--force", str(project_path)]
        mode = "pipx"
    else:
        command = [sys.executable, "-m", "pip", "install", "--user", "--upgrade", str(project_path)]
        mode = "pip --user"

    print(f"reinstalling from {project_path} using {mode}")
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
