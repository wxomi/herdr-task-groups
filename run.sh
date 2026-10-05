#!/usr/bin/env bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export PYTHONPATH="/Users/wxomi/.local/share/herdr-task-groups:${PYTHONPATH:-}"

if [ "$1" = "open" ]; then
    HERDR="${HERDR_BIN_PATH:-/opt/homebrew/bin/herdr}"
    exec "$HERDR" plugin pane open --plugin wxomi.task-groups --entrypoint group-palette --placement overlay
fi

exec /opt/homebrew/bin/python3 -m task_groups "$@"
