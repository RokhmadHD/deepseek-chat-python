from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .logging_config import get_logger, setup_logging
from .session_store import DEFAULT_PROFILE, default_db_path, project_root, save_capture_to_db

log = get_logger("login")


DEFAULT_URL = "https://chat.deepseek.com"
DEFAULT_CAMOUFOX = "/home/tensanq/.cache/camoufox/camoufox"
AUTH_COOKIE_NAMES = {"ds_session_id"}
LOGIN_FORM_SELECTORS = [
    ".ds-sign-in-form-wrapper",
    'input[placeholder="Phone number / email address"]',
    'input[placeholder="Password"]',
]
APP_READY_SELECTORS = [
    "textarea",
    '[contenteditable="true"]',
    'input[placeholder*="message" i]',
    "text=New chat",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Login to DeepSeek web and save auth session to SQLite.")
    parser.add_argument("--url", default=DEFAULT_URL, help="DeepSeek start URL.")
    parser.add_argument("--output-dir", default=None, help="Capture output dir. Defaults to captures/deepseek-login-<timestamp>.")
    parser.add_argument("--browser-path", default=os.getenv("CAMOUFOX_BIN"), help="Browser executable path. Defaults to Camoufox if present.")
    parser.add_argument("--headless", action="store_true", help="Run browser headless.")
    parser.add_argument("--manual", action="store_true", help="Wait for Enter before saving instead of auto-detecting login.")
    parser.add_argument("--wait-timeout", type=int, default=180, help="Seconds to wait for login auto-detection.")
    parser.add_argument("--profile", default=DEFAULT_PROFILE, help="SQLite auth profile to replace. Defaults to default.")
    parser.add_argument("--no-db", action="store_true", help="Save capture only; do not update SQLite.")
    return parser.parse_args()


def any_visible(page: Any, selectors: list[str]) -> bool:
    for selector in selectors:
        try:
            loc = page.locator(selector)
            if loc.count() > 0 and loc.first.is_visible():
                return True
        except Exception:
            continue
    return False


def active_pages(context: Any) -> list[Any]:
    return [page for page in context.pages if not page.is_closed()]


def has_auth_cookie(context: Any) -> bool:
    try:
        cookies = context.cookies([DEFAULT_URL])
    except TypeError:
        cookies = context.cookies()
    return any(cookie.get("name") in AUTH_COOKIE_NAMES for cookie in cookies)


def wait_for_login(context: Any, timeout_seconds: int) -> bool:
    deadline = time.monotonic() + timeout_seconds
    next_notice = 0.0

    while time.monotonic() < deadline:
        pages = active_pages(context)
        ready_page = None
        login_form_visible = False

        for page in pages:
            login_form_visible = login_form_visible or any_visible(page, LOGIN_FORM_SELECTORS)
            if any_visible(page, APP_READY_SELECTORS):
                ready_page = page

        if has_auth_cookie(context) and (ready_page or not login_form_visible):
            return True

        now = time.monotonic()
        if now >= next_notice:
            remaining = int(deadline - now)
            print(f"[login] waiting for login to finish... {remaining}s left")
            next_notice = now + 10

        if pages:
            try:
                pages[-1].wait_for_timeout(1000)
                continue
            except Exception:
                pass
        time.sleep(1)
    return False


def dump_page_state(page: Any) -> dict[str, Any]:
    try:
        return page.evaluate(
            """() => ({
                url: location.href,
                origin: location.origin,
                title: document.title,
                userAgent: navigator.userAgent,
                localStorage: Object.fromEntries(Object.entries(localStorage)),
                sessionStorage: Object.fromEntries(Object.entries(sessionStorage)),
            })"""
        )
    except Exception as exc:
        return {"url": page.url, "error": str(exc)}


def launch_browser(playwright: Any, browser_path: str | None, headless: bool) -> Any:
    if browser_path:
        path = Path(browser_path).expanduser()
        print(f"[login] browser={path}")
        log.info("launching firefox browser=%s headless=%s", path, headless)
        return playwright.firefox.launch(executable_path=str(path), headless=headless)
    camoufox = Path(DEFAULT_CAMOUFOX)
    if camoufox.exists():
        print(f"[login] browser={camoufox}")
        log.info("launching camoufox browser=%s headless=%s", camoufox, headless)
        return playwright.firefox.launch(executable_path=str(camoufox), headless=headless)
    print("[login] browser=playwright chromium")
    log.info("launching playwright chromium headless=%s", headless)
    return playwright.chromium.launch(headless=headless)


def main() -> None:
    log_file = setup_logging()
    args = parse_args()
    root = project_root()
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else root / "captures" / f"deepseek-login-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[login] output_dir={output_dir}")
    print(f"[login] url={args.url}")
    log.info("login start profile=%s output_dir=%s url=%s", args.profile, output_dir, args.url)

    try:
        with sync_playwright() as playwright:
            browser = launch_browser(playwright, args.browser_path, args.headless)
            context = browser.new_context()
            page = context.new_page()
            page.goto(args.url, wait_until="domcontentloaded")

            if args.manual:
                print("Login di browser, lalu kembali ke terminal dan tekan Enter.")
                input("Press Enter when login is done...")
            else:
                print("Login di browser. Setelah session siap, capture akan auto-save.")
                if not wait_for_login(context, args.wait_timeout):
                    browser.close()
                    raise SystemExit(f"Login tidak terdeteksi dalam {args.wait_timeout}s. Coba ulang dengan --manual.")

            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except PlaywrightTimeoutError:
                pass

            storage_state_path = output_dir / "storage-state.json"
            context.storage_state(path=str(storage_state_path))
            (output_dir / "cookies.json").write_text(json.dumps(context.cookies(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            page_state = dump_page_state(page)
            (output_dir / "page-storage.json").write_text(json.dumps(page_state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            pages = [dump_page_state(item) for item in context.pages if not item.is_closed()]
            (output_dir / "pages.json").write_text(json.dumps(pages, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            (output_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "captured_at": datetime.now().isoformat(),
                        "url": args.url,
                        "artifacts": {
                            "storage_state": str(storage_state_path),
                            "page_storage": str(output_dir / "page-storage.json"),
                        },
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            browser.close()

        print(f"[login] saved capture to {output_dir}")
        if not args.no_db:
            session = save_capture_to_db(output_dir, profile=args.profile)
            print(f"[login] saved profile={session.profile} to {default_db_path()}")
            log.info("saved sqlite profile=%s db=%s", session.profile, default_db_path())
    except Exception:
        log.exception("login failed")
        print(f"[login] log={log_file}")
        raise


if __name__ == "__main__":
    main()
