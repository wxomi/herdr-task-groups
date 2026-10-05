"""Task Groups: clustering, summary pill generation, and collapse state."""

from __future__ import annotations

import collections
import json
import os
import re
from typing import TYPE_CHECKING

from task_groups.config import GROUP_STATE_FILE, SOURCE, STATE_DIR

if TYPE_CHECKING:
    from task_groups.client import HerdrClient


def format_agent_path(cwd: str | None) -> str | None:
    """Format a working directory as ~ or the project basename."""
    if not cwd:
        return None
    try:
        path = os.path.realpath(os.path.expanduser(cwd))
    except OSError:
        return None
    home = os.path.realpath(os.path.expanduser("~"))
    if path == home:
        return "~"
    name = os.path.basename(path)
    return name or path


def get_canonical_group_name(workspace_label: str) -> str:
    """Extract root project/task group from workspace label by stripping '-agents'."""
    if not workspace_label:
        return ""
    home_dir = os.path.expanduser("~")
    if workspace_label == home_dir or workspace_label == f"{home_dir}-agents":
        return "~"
    if workspace_label.endswith("-agents"):
        return workspace_label[:-7]
    return workspace_label


def cluster_agents_by_group(snapshot: dict) -> dict[str, list[dict]]:
    """Group agents by custom assignment first, project cwd second, workspace third."""
    state = load_group_state()
    custom_groups = state.get("custom_groups", {})
    ungrouped = set(state.get("ungrouped_panes", []))

    workspaces = snapshot.get("workspaces", [])
    ws_to_group: dict[str, str] = {}
    for ws in workspaces:
        ws_id = ws.get("workspace_id")
        label = ws.get("label", "")
        if ws_id:
            ws_to_group[ws_id] = get_canonical_group_name(label)

    agents = snapshot.get("agents", [])
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for a in agents:
        pid = a.get("pane_id")
        # 1. Explicitly ungrouped (standalone solo agent)
        if pid and pid in ungrouped:
            groups[f"_solo_{pid}"].append(a)
            continue

        # 2. Explicitly moved to custom group
        if pid and pid in custom_groups:
            group = custom_groups[pid]
            groups[group].append(a)
            continue

        # 3. Dedicated task workspace (anything other than base devel/~ workspaces)
        ws_id = a.get("workspace_id")
        ws_label = ws_to_group.get(ws_id)
        if ws_label and ws_label not in ("devel", "~", "agents"):
            groups[ws_label].append(a)
            continue

        # 4. Default: project directory or base workspace
        cwd = a.get("cwd") or a.get("foreground_cwd")
        project = format_agent_path(cwd) if cwd else None
        if project:
            group = project
        else:
            group = ws_label or "default"
        groups[group].append(a)

    return dict(groups)


def clean_agent_title(title: str) -> str:
    """Strip group collapse indicators, agent counts, and nested prefixes."""
    t = (title or "").strip()
    while True:
        prev = t
        t = re.sub(r"^[▶▼]\s*", "", t)
        t = re.sub(r"\s*\(\d+\s+agents?\)$", "", t)
        t = re.sub(r"^[~a-zA-Z0-9_-]+\s*·\s*", "", t)
        t = t.strip()
        if t == prev:
            break
    return t


def extract_common_task_topic(agents: list[dict]) -> str:
    """Extract a concise common task/topic from agent session titles if one exists."""
    raw_titles = []
    for a in agents:
        raw = (a.get("tokens") or {}).get("session") or a.get("title") or ""
        if raw.startswith("▶") or raw.startswith("▼"):
            continue
        clean = clean_agent_title(raw)
        if clean:
            raw_titles.append(clean)

    titles = [t for t in raw_titles if t]
    if not titles:
        return ""
    if len(titles) == 1:
        return titles[0][:32]

    if all(t == titles[0] for t in titles):
        return titles[0][:32]

    task_patterns = [
        re.compile(r"\b(T\d{4,7})\b", re.IGNORECASE),
        re.compile(r"\b([A-Z]{2,10}-\d+)\b"),
        re.compile(r"\b(#\d+)\b"),
    ]
    for pat in task_patterns:
        matches = [pat.search(t) for t in titles]
        if all(m is not None for m in matches):
            vals = {m.group(1).upper() for m in matches if m}
            if len(vals) == 1:
                return f"Task {vals.pop()}"

    first = titles[0]
    prefix_words = []
    words_first = first.split()
    for idx, w in enumerate(words_first):
        if all(
            idx < len(t.split()) and t.split()[idx].lower() == w.lower()
            for t in titles[1:]
        ):
            prefix_words.append(w)
        else:
            break
    if len(prefix_words) >= 2:
        return " ".join(prefix_words)[:32]

    return ""


def get_group_summary_info(
    group_name: str,
    agents: list[dict],
    is_custom: bool = False,
) -> tuple[str, str]:
    """Generate collapsed group summary title and location indicator string."""
    count = len(agents)
    common_topic = extract_common_task_topic(agents)

    if is_custom:
        title = f"▶ {group_name} ({count} agents)"
    elif common_topic:
        title = f"▶ {common_topic} ({count} agents)"
    else:
        title = f"▶ {group_name} ({count} agents)"

    working = sum(
        1
        for a in agents
        if (a.get("agent_status") or a.get("status") or "").lower() == "working"
    )
    blocked = sum(
        1
        for a in agents
        if (a.get("agent_status") or a.get("status") or "").lower() == "blocked"
    )
    idle = count - working - blocked

    status_parts = []
    if working > 0:
        status_parts.append(f"{working} working")
    if blocked > 0:
        status_parts.append(f"{blocked} blocked")
    if idle > 0:
        status_parts.append(f"{idle} idle")

    status_str = ", ".join(status_parts) if status_parts else "idle"
    location = f"{group_name} · {status_str}" if group_name != "~" else status_str
    return title, location


def load_group_state() -> dict:
    """Read group collapsed/expanded state, custom group mappings, and ungrouped panes."""
    default_state = {"collapsed_groups": [], "custom_groups": {}, "ungrouped_panes": []}
    if not os.path.exists(GROUP_STATE_FILE):
        return default_state
    try:
        with open(GROUP_STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("collapsed_groups", [])
                data.setdefault("custom_groups", {})
                data.setdefault("ungrouped_panes", [])
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return default_state


def save_group_state(state: dict) -> None:
    """Save group collapsed/expanded state to JSON file."""
    os.makedirs(STATE_DIR, exist_ok=True)
    temp_path = f"{GROUP_STATE_FILE}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(temp_path, GROUP_STATE_FILE)
    except OSError:
        pass


def is_group_collapsed(group_name: str) -> bool:
    """Check if a task group is currently collapsed."""
    state = load_group_state()
    return group_name in state.get("collapsed_groups", [])


def toggle_group_collapse(group_name: str) -> bool:
    """Toggle collapse state for a group. Returns True if now collapsed, False if expanded."""
    state = load_group_state()
    collapsed = set(state.get("collapsed_groups", []))
    if group_name in collapsed:
        collapsed.remove(group_name)
        is_now_collapsed = False
    else:
        collapsed.add(group_name)
        is_now_collapsed = True
    state["collapsed_groups"] = sorted(collapsed)
    save_group_state(state)
    return is_now_collapsed


def collapse_all_groups(groups: list[str]) -> None:
    """Mark all listed groups as collapsed."""
    state = load_group_state()
    state["collapsed_groups"] = sorted(set(groups))
    save_group_state(state)


def expand_all_groups() -> None:
    """Expand all groups (un-collapse everything)."""
    state = load_group_state()
    state["collapsed_groups"] = []
    save_group_state(state)


def move_agent_to_group(pane_id: str, group_name: str) -> None:
    """Move an agent into an existing or new task group."""
    state = load_group_state()
    custom = state.setdefault("custom_groups", {})
    ungrouped = set(state.setdefault("ungrouped_panes", []))

    custom[pane_id] = group_name.strip()
    ungrouped.discard(pane_id)
    state["ungrouped_panes"] = sorted(ungrouped)
    save_group_state(state)


def ungroup_agent(pane_id: str) -> None:
    """Remove an agent from its group to make it standalone."""
    state = load_group_state()
    custom = state.setdefault("custom_groups", {})
    ungrouped = set(state.setdefault("ungrouped_panes", []))

    custom.pop(pane_id, None)
    ungrouped.add(pane_id)
    state["ungrouped_panes"] = sorted(ungrouped)
    save_group_state(state)


def reset_agent_group(pane_id: str) -> None:
    """Reset agent back to automatic directory/workspace grouping."""
    state = load_group_state()
    custom = state.setdefault("custom_groups", {})
    ungrouped = set(state.setdefault("ungrouped_panes", []))

    custom.pop(pane_id, None)
    ungrouped.discard(pane_id)
    state["ungrouped_panes"] = sorted(ungrouped)
    save_group_state(state)


def move_group_to_workspace(
    client: HerdrClient,
    group_name: str,
    target_workspace_name: str,
) -> int:
    """Move all agents in a group to a target workspace."""
    if not client.is_available():
        return 0
    snap = client.snapshot()
    groups = cluster_agents_by_group(snap)
    group_agents = groups.get(group_name, [])
    if not group_agents:
        return 0

    target_ws_id = client.get_or_create_workspace(target_workspace_name)
    if not target_ws_id:
        return 0

    moved_count = 0
    for ag in group_agents:
        pid = ag.get("pane_id")
        if pid and ag.get("workspace_id") != target_ws_id:
            if client.move_pane_to_workspace(pid, target_ws_id):
                moved_count += 1
    return moved_count


def is_workspace_scoped() -> bool:
    """Check if the sidebar is currently scoped to the active workspace."""
    state = load_group_state()
    return state.get("scope_workspace", True)


def toggle_workspace_scope() -> bool:
    """Toggle between scoping the sidebar to the current workspace vs showing all."""
    state = load_group_state()
    current = state.get("scope_workspace", True)
    state["scope_workspace"] = not current
    save_group_state(state)
    return state["scope_workspace"]


_LAST_APPLIED_VIEW_KEY: tuple | None = None
_LAST_SUMMARY_TOKENS: dict[str, str] = {}


def apply_collapsible_groups(
    client: HerdrClient,
    snap: dict | None = None,
    force: bool = False,
) -> bool:
    """Evaluate task groups, update collapsed group summary tokens, and apply Herdr pane filter."""
    global _LAST_APPLIED_VIEW_KEY, _LAST_SUMMARY_TOKENS
    if not client.is_available():
        return False

    snapshot = snap if snap is not None else client.snapshot()
    if not snapshot:
        return False

    groups = cluster_agents_by_group(snapshot)
    if not groups:
        return True

    state = load_group_state()
    collapsed_groups = set(state.get("collapsed_groups", []))
    custom_groups = state.get("custom_groups", {})
    custom_group_names = set(custom_groups.values())
    scoped = state.get("scope_workspace", True)

    visible_pane_ids: list[str] = []
    has_any_collapsed = False

    for group_name, agents in groups.items():
        if not agents:
            continue
        is_custom = group_name in custom_group_names

        if group_name in collapsed_groups and len(agents) > 1:
            has_any_collapsed = True
            first_pane = agents[0]
            pid = first_pane.get("pane_id")
            if pid:
                visible_pane_ids.append(pid)
                title, location = get_group_summary_info(
                    group_name, agents, is_custom=is_custom
                )
                curr_session = (first_pane.get("tokens") or {}).get("session")
                if force or _LAST_SUMMARY_TOKENS.get(pid) != title or curr_session != title:
                    client.report_metadata(
                        pid,
                        SOURCE,
                        {"session": title, "location": location},
                        title=title,
                        display_agent=title,
                    )
                    _LAST_SUMMARY_TOKENS[pid] = title
        else:
            for a in agents:
                pid = a.get("pane_id")
                if pid:
                    visible_pane_ids.append(pid)
                    _LAST_SUMMARY_TOKENS.pop(pid, None)

    sorted_visible = sorted(visible_pane_ids)

    if has_any_collapsed:
        pane_filter = {"op": "in", "field": "pane_id", "values": sorted_visible}
        if scoped:
            target_filter = {
                "op": "all",
                "filters": [
                    {
                        "op": "eq",
                        "field": "workspace_id",
                        "value": {"context": "current_workspace_id"},
                    },
                    pane_filter,
                ],
            }
            view_label = "this workspace"
            cache_key = ("scoped_grouped", tuple(sorted_visible))
        else:
            target_filter = pane_filter
            view_label = "grouped"
            cache_key = ("grouped", tuple(sorted_visible))

        if force or _LAST_APPLIED_VIEW_KEY != cache_key:
            ok = client.set_agent_view(SOURCE, view_label, target_filter)
            if ok:
                _LAST_APPLIED_VIEW_KEY = cache_key
            return ok
        return True
    else:
        if scoped:
            cache_key = ("scoped_all", ())
            if force or _LAST_APPLIED_VIEW_KEY != cache_key:
                ok = client.set_agent_view(
                    SOURCE,
                    "this workspace",
                    {
                        "op": "eq",
                        "field": "workspace_id",
                        "value": {"context": "current_workspace_id"},
                    },
                )
                if ok:
                    _LAST_APPLIED_VIEW_KEY = cache_key
                    _LAST_SUMMARY_TOKENS.clear()
                return ok
            return True
        else:
            if force or _LAST_APPLIED_VIEW_KEY is not None:
                ok = client.clear_agent_view(SOURCE)
                if ok:
                    _LAST_APPLIED_VIEW_KEY = None
                    _LAST_SUMMARY_TOKENS.clear()
                return ok
            return True
