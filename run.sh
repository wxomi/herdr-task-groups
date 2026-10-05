#!/usr/bin/env bash
export PYTHONPATH="/Users/wxomi/.local/share/herdr-task-groups:${PYTHONPATH:-}"
exec /opt/homebrew/bin/python3 -m task_groups "$@"
