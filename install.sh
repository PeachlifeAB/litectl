#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/litectl"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v uv >/dev/null 2>&1; then
    curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="${HOME}/.local/bin:${PATH}"
fi

uv tool install --force "${SCRIPT_DIR}"
TOOL_BIN="$(uv tool dir --bin)/litectl"
"${TOOL_BIN}" install "${TARGET_DIR}"
