# deepseek-chat-python

Minimal Python client for regular chat with DeepSeek web.

This project is intentionally small for now: no OpenAI-compatible server, but it does include a compact tool-calling loop, a TUI, and local workspace tools.

## Support Development

If you find this project useful, consider supporting its development:

[![Saweria](https://img.shields.io/badge/Saweria-Support-orange?style=for-the-badge&logo=ko-fi&logoColor=white)](https://saweria.co/RokhmadHD)


## Features

- Creates a new chat session through `/api/v0/chat_session/create`.
- Fetches the PoW challenge through `/api/v0/chat/create_pow_challenge`.
- Solves PoW with DeepSeek's official wasm.
- Sends prompts to `/api/v0/chat/completion`.
- Parses DeepSeek SSE responses and drives tool-call responses.
- Can be used as a one-shot command or in interactive mode.

## Requirements

- Python 3.11 or newer.
- A valid DeepSeek web session.
- Network access to install dependencies and download the PoW wasm on first use.

## Setup

```bash
cd ~/deepseek-chat-python
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
cp .env.example .env
```

`.env` is only for non-secret configuration. Login tokens and cookies are stored in SQLite.

If you want the commands available globally without activating a virtualenv, run:

```bash
bash install.sh
```

That installs the package with `pipx` when available, or falls back to `python3 -m pip install --user .`.

Login:

```bash
deepseek-chat-login
```

This command opens a browser. Wait until you are logged in to DeepSeek web, then it stores captures in `captures/` and auth data in `.data/session.db`. If you log in again, the same profile will be replaced. By default, this command uses Camoufox at `/home/tensanq/.cache/camoufox/camoufox` if that binary exists.

To force a specific Camoufox path:

```bash
CAMOUFOX_BIN=/home/tensanq/.cache/camoufox/camoufox deepseek-chat-login
```

If login auto-detection fails, use manual mode:

```bash
deepseek-chat-login --manual
```

Other profiles:

```bash
deepseek-chat-login --profile kerja
deepseek-chat --profile kerja "hello"
deepseek-chat-tui --profile kerja
```

If Playwright browsers are not installed on the machine:

```bash
python3 -m playwright install chromium
```

## Usage

Global command:

```bash
deepseek login
deepseek status
deepseek tui
deepseek reinstall
```

One-shot command:

```bash
deepseek-chat "hello"
```

Check whether the current profile is logged in:

```bash
deepseek-chat status
deepseek status --json
```

Interactive mode:

```bash
deepseek-chat
```

In interactive mode, the session and `parent_message_id` are preserved while the process is alive, so the conversation continues in the same thread.

Terminal TUI:

```bash
deepseek tui
deepseek tui resume
```

The TUI uses Textual. Controls:

- `Enter` to send a message.
- Large or multiline pastes are shown as `[pasted for ... chars]` but sent with the full pasted text.
- `/attach /path/to/file` to upload a document and attach it to future prompts.
- `/files` to list attached files.
- `/clear-files` to clear attached files.
- `/copy`, `/copy last`, `/copy user`, or `/copy all` to copy chat text to clipboard.
- `/copy raw` to write a raw transcript file under `.logs/`.
- `/model` to toggle `model_type` between `default` and `expert`.
- `/model default` to use the default model type.
- `/model expert` to use the expert model type.
- `/quit`, `/exit`, or `/q` to exit.
- `Ctrl+L` to clear the chat.

`deepseek tui resume` shows saved chat sessions for the active profile, lets you move with arrow keys, and opens the selected session.

TUI responses are displayed progressively like streaming. For now, the HTTP request is still non-streaming, so text starts appearing after the full response is received from DeepSeek.

While a request is running, the TUI shows a loader/spinner in the status bar and assistant label.

The TUI shows chat on the left and estimated token statistics on the right. The stats panel includes the last response duration, estimated output tokens, tokens/s, estimated cost, session totals, and a compact command list. It auto-hides on narrow terminals. The cost estimate uses `DEEPSEEK_ESTIMATED_OUTPUT_COST_PER_1M_TOKENS_USD`.

## Configuration

Important env vars:

| Env | Default | Description |
| --- | --- | --- |
| `DEEPSEEK_API_BASE` | `https://chat.deepseek.com` | Base URL DeepSeek web. |
| `DEEPSEEK_MODEL_TYPE` | `default` | Model type sent to DeepSeek. |
| `DEEPSEEK_SEARCH_ENABLED` | `true` | Enables search in chat requests. |
| `DEEPSEEK_THINKING_ENABLED` | `false` | Enables thinking mode. |
| `DEEPSEEK_SYSTEM_PROMPT_ENABLED` | `true` | Injects `deepseek_chat/settings/system.md` into new chat sessions. |
| `DEEPSEEK_SYSTEM_PROMPT_PATH` | `deepseek_chat/settings/system.md` | Optional override for the system prompt file. |
| `DEEPSEEK_MAX_TOOL_ROUNDS` | `4` | Maximum tool-call iterations before returning the latest model output. |
| `DEEPSEEK_TOOL_RESULT_MAX_BYTES` | `120000` | Maximum serialized tool result size sent back to DeepSeek. |
| `DEEPSEEK_PREEMPT` | `false` | Request `preempt` value. |
| `DEEPSEEK_POW_WASM_CACHE` | `.cache/sha3_wasm_bg.7b9ca65ddd.wasm` | PoW wasm cache location. |
| `SEARXNG_URL` | `http://localhost:8080` | Base URL for local SearXNG-backed tools. |
| `SEARXNG_LANGUAGE` | `en` | Default SearXNG search language. |

Login auth is stored in `.data/session.db` and is not committed to git.

## Tools

The `tools` package contains callable tool implementations and JSON schemas for future tool-calling integration.

- `search_web`: searches one query through SearXNG.
- `multi_search`: searches multiple queries through SearXNG and deduplicates URLs for deep search.
- `list_dir`, `tree_dir`, `read_file`, `search_files`, `write_file`: workspace-scoped filesystem tools. `write_file` asks for TUI approval before it executes.
- `git_status`, `git_diff`, `git_log`: read-only project state tools.
- `run_command`: allowlisted project commands such as compile checks, pytest, and read-only git commands.
- `get_time`, `calculate`, `json_validate`, `format_json`: utility tools.

## Troubleshooting

If you get `401` or `403`, the auth/cookie is likely expired or incomplete. Run `deepseek-chat-login` again to replace the SQLite session.

If an error occurs while downloading the wasm, check the network and rerun the command. The wasm file will be cached in `.cache/`.

If the `deepseek-chat` command is not found, make sure the virtualenv is active and `pip install -e .` completed successfully.

If `deepseek-chat-login` fails to open a browser, make sure Camoufox still exists at `/home/tensanq/.cache/camoufox/camoufox`, or set `CAMOUFOX_BIN=/path/to/camoufox`. Last fallback: install a Playwright browser with `python3 -m playwright install chromium`.

Error logs are written to `.logs/deepseek-chat.log`.

## Status

This version is an early port for regular chat. The parser from the old project was intentionally left out for now so the client foundation stays simpler and easier to test.
