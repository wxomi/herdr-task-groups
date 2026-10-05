#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"

HERDR="${HERDR_BIN_PATH:-$(command -v herdr 2>/dev/null || echo "$HOME/.local/bin/herdr")}"
PYTHON="$(command -v python3 2>/dev/null || echo "python3")"

if [ "$1" = "open" ]; then
    exec "$HERDR" plugin pane open --plugin wxomi.task-groups --entrypoint group-palette --placement overlay
fi

exec "$PYTHON" -m task_groups "$@"
