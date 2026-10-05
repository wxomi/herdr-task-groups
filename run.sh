#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"

HERDR="${HERDR_BIN_PATH:-$(command -v herdr 2>/dev/null || echo "$HOME/.local/bin/herdr")}"
PYTHON="$(command -v python3 2>/dev/null || echo "python3")"

if [ "$1" = "open" ]; then
    ENV_ARGS=()
    WS="${HERDR_WORKSPACE_ID:-}"
    PANE="${HERDR_PANE_ID:-}"
    if [ -z "$WS" ] && [ -n "${HERDR_PLUGIN_CONTEXT_JSON:-}" ]; then
        WS=$(echo "$HERDR_PLUGIN_CONTEXT_JSON" | grep -o '"workspace_id":"[^"]*"' | cut -d'"' -f4)
    fi
    if [ -z "$PANE" ] && [ -n "${HERDR_PLUGIN_CONTEXT_JSON:-}" ]; then
        PANE=$(echo "$HERDR_PLUGIN_CONTEXT_JSON" | grep -o '"focused_pane_id":"[^"]*"' | cut -d'"' -f4)
    fi
    if [ -n "$WS" ]; then
        ENV_ARGS+=(--env "TARGET_WORKSPACE=$WS" --env "HERDR_WORKSPACE_ID=$WS")
    fi
    if [ -n "$PANE" ]; then
        ENV_ARGS+=(--env "TARGET_PANE=$PANE" --env "HERDR_PANE_ID=$PANE")
    fi
    exec "$HERDR" plugin pane open --plugin wxomi.task-groups --entrypoint group-palette --placement overlay "${ENV_ARGS[@]}"
fi

exec "$PYTHON" -m task_groups "$@"

