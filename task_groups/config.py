"""Configuration constants and paths for Herdr Task Groups."""

from __future__ import annotations

import os

SOURCE = "wxomi.task-groups"

HERDR_SOCKET_PATH = os.path.expanduser(
    os.environ.get("HERDR_SOCKET_PATH", "~/.config/herdr/herdr.sock")
)

STATE_DIR = os.path.expanduser(
    os.environ.get(
        "HERDR_TASK_GROUPS_STATE_DIR",
        "~/.config/herdr/plugins/task_groups",
    )
)

GROUP_STATE_FILE = os.path.join(STATE_DIR, "group_state.json")
