# deepseek-chat-python

Minimal Python client for regular chat with DeepSeek web.

This project is intentionally small for now: no parser, no OpenAI-compatible server, and no tool calling yet. The focus is only sending prompts to DeepSeek web and printing text responses.

## Support Development

If you find this project useful, consider supporting its development:

[![Saweria](https://img.shields.io/badge/Saweria-Support-orange?style=for-the-badge&logo=ko-fi&logoColor=white)](https://saweria.co/RokhmadHD)


## Features

- Creates a new chat session through `/api/v0/chat_session/create`.
- Fetches the PoW challenge through `/api/v0/chat/create_pow_challenge`.
- Solves PoW with DeepSeek's official wasm.
- Sends prompts to `/api/v0/chat/completion`.
- Parses DeepSeek SSE responses into plain text.
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

One-shot command:

```bash
deepseek-chat "hello"
```

Interactive mode:

```bash
deepseek-chat
```

In interactive mode, the session and `parent_message_id` are preserved while the process is alive, so the conversation continues in the same thread.

Terminal TUI:

```bash
deepseek-chat-tui
```

The TUI uses Textual. Controls:

- `Enter` to send a message.
- `/model` to toggle `model_type` between `default` and `expert`.
- `/model default` to use the default model type.
- `/model expert` to use the expert model type.
- `/quit`, `/exit`, or `/q` to exit.
- `Ctrl+L` to clear the chat.

TUI responses are displayed progressively like streaming. For now, the HTTP request is still non-streaming, so text starts appearing after the full response is received from DeepSeek.

While a request is running, the TUI shows a loader/spinner in the status bar and assistant label.

Below each AI response, the TUI shows metrics from left to right: duration, estimated output tokens, tokens/s, and estimated cost. The cost estimate uses `DEEPSEEK_ESTIMATED_OUTPUT_COST_PER_1M_TOKENS_USD`.

## Configuration

Important env vars:

| Env | Default | Description |
| --- | --- | --- |
| `DEEPSEEK_API_BASE` | `https://chat.deepseek.com` | Base URL DeepSeek web. |
| `DEEPSEEK_MODEL_TYPE` | `default` | Model type sent to DeepSeek. |
| `DEEPSEEK_SEARCH_ENABLED` | `true` | Enables search in chat requests. |
| `DEEPSEEK_THINKING_ENABLED` | `false` | Enables thinking mode. |
| `DEEPSEEK_PREEMPT` | `false` | Request `preempt` value. |
| `DEEPSEEK_POW_WASM_CACHE` | `.cache/sha3_wasm_bg.7b9ca65ddd.wasm` | PoW wasm cache location. |

Login auth is stored in `.data/session.db` and is not committed to git.

## Troubleshooting

If you get `401` or `403`, the auth/cookie is likely expired or incomplete. Run `deepseek-chat-login` again to replace the SQLite session.

If an error occurs while downloading the wasm, check the network and rerun the command. The wasm file will be cached in `.cache/`.

If the `deepseek-chat` command is not found, make sure the virtualenv is active and `pip install -e .` completed successfully.

If `deepseek-chat-login` fails to open a browser, make sure Camoufox still exists at `/home/tensanq/.cache/camoufox/camoufox`, or set `CAMOUFOX_BIN=/path/to/camoufox`. Last fallback: install a Playwright browser with `python3 -m playwright install chromium`.

Error logs are written to `.logs/deepseek-chat.log`.

## Status

This version is an early port for regular chat. The parser from the old project was intentionally left out for now so the client foundation stays simpler and easier to test.
