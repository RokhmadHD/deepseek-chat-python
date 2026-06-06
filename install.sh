#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but was not found in PATH." >&2
  exit 1
fi

install_with_pipx() {
  if command -v pipx >/dev/null 2>&1; then
    pipx install --force .
    return 0
  fi
  return 1
}

install_with_user_pip() {
  python3 -m pip install --user --upgrade .
}

if install_with_pipx; then
  echo "Installed deepseek commands using pipx."
else
  echo "pipx not found, falling back to python3 -m pip install --user ..."
  install_with_user_pip
  echo "Installed deepseek commands with --user site-packages."
fi

echo
echo "Available commands:"
echo "  deepseek"
echo "  deepseek-chat"
echo "  deepseek-chat-login"
echo "  deepseek-chat-tui"
echo
if ! command -v deepseek >/dev/null 2>&1; then
  echo "If the commands are not found, add this directory to PATH:" >&2
  echo "  ~/.local/bin" >&2
fi
