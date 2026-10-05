"""CLI entrypoint and interactive multi-select fzf palette for Herdr Task Groups."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time

from task_groups.client import HerdrClient
from task_groups.groups import (
    apply_collapsible_groups,
    cluster_agents_by_group,
    collapse_all_groups,
    expand_all_groups,
    get_group_summary_info,
    load_group_state,
    is_workspace_scoped,
    move_agent_to_group,
    move_group_to_workspace,
    reset_agent_group,
    toggle_group_collapse,
    toggle_workspace_scope,
    ungroup_agent,
)


def run_picker(prompt: str, items: list[str], multi: bool = False) -> list[str]:
    """Show an interactive selection menu using fzf if available, else numeric stdin prompt."""
    fzf_bin = shutil.which("fzf") or (
        "/opt/homebrew/bin/fzf" if os.path.exists("/opt/homebrew/bin/fzf") else None
    )

    if fzf_bin and sys.stdin.isatty():
        try:
            cmd = [
                fzf_bin,
                "--prompt",
                f"{prompt} > ",
                "--height",
                "50%",
                "--layout=reverse",
                "--border",
                "--cycle",
            ]
            if multi:
                cmd.extend(["--multi", "--bind=ctrl-a:select-all,ctrl-d:deselect-all"])
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
            )
            out, _ = proc.communicate(input="\n".join(items) + "\n")
            if proc.returncode == 0 and out.strip():
                return [line.strip() for line in out.strip().splitlines() if line.strip()]
            return []
        except Exception:
            pass

    print(f"\n{prompt}")
    for idx, it in enumerate(items, 1):
        print(f"  [{idx}] {it}")
    print("  [q] Cancel\n")
    try:
        choice = input("Enter selection (comma-separated for multi): ").strip()
        if not choice or choice.lower() == "q":
            return []
        selected = []
        for part in choice.split(","):
            part = part.strip()
            if part.isdigit():
                num = int(part)
                if 1 <= num <= len(items):
                    selected.append(items[num - 1])
            else:
                for it in items:
                    if part.lower() in it.lower():
                        selected.append(it)
                        break
        return selected
    except (EOFError, KeyboardInterrupt):
        return []


def interactive_pick_group(
    client: HerdrClient,
    pane_id: str | None = None,
    all_workspaces: bool = False,
) -> int:
    """Interactively select agent(s) and move them into a dedicated task workspace."""
    snap = client.snapshot() if client.is_available() else {}
    agents = snap.get("agents", [])
    if not agents:
        print("No active agents found in Herdr.")
        return 1

    state = load_group_state()
    custom_groups = state.get("custom_groups", {})

    f_pid = (
        pane_id
        or os.environ.get("TARGET_PANE")
        or os.environ.get("HERDR_PANE_ID")
        or snap.get("focused_pane_id")
    )

    # Determine caller workspace to scope the agent list
    target_ws = (
        os.environ.get("TARGET_WORKSPACE")
        or os.environ.get("HERDR_WORKSPACE_ID")
        or snap.get("focused_workspace_id")
    )
    if not target_ws and f_pid:
        target_ws = f_pid.split(":")[0]

    ws_list = snap.get("workspaces", [])
    ws_map = {w.get("workspace_id"): w.get("label", "") for w in ws_list if w.get("workspace_id")}

    allowed_ws_ids: set[str] = set()
    if target_ws and not all_workspaces:
        allowed_ws_ids.add(target_ws)
        target_label = ws_map.get(target_ws, "")
        if target_label:
            if target_label.endswith("-agents"):
                base_label = target_label[:-7]
                for w_id, w_lbl in ws_map.items():
                    if w_lbl == base_label:
                        allowed_ws_ids.add(w_id)
            else:
                comp_label = f"{target_label}-agents"
                for w_id, w_lbl in ws_map.items():
                    if w_lbl == comp_label:
                        allowed_ws_ids.add(w_id)

    # Sort agents: focused pane first
    sorted_agents = sorted(
        agents,
        key=lambda a: (0 if a.get("pane_id") == f_pid else 1, a.get("pane_id", ""))
    )

    if allowed_ws_ids:
        active_agents = [a for a in sorted_agents if a.get("workspace_id") in allowed_ws_ids]
    else:
        active_agents = sorted_agents

    has_more = len(active_agents) < len(sorted_agents)

    # If no agents match the current workspace, fall back to all agents
    if not active_agents:
        active_agents = sorted_agents
        has_more = False

    agent_choices = []
    for a in active_agents:
        pid = a.get("pane_id", "")
        agent_type = a.get("agent", "agent")
        title = (a.get("tokens") or {}).get("session") or a.get("title", "")
        cwd = a.get("cwd", "")
        short_cwd = cwd.split("/")[-1] if cwd else "~"
        current_g = custom_groups.get(pid)
        group_badge = f" [Workspace: {current_g}]" if current_g else ""
        is_focused = " (focused)" if pid == f_pid else ""
        agent_choices.append(f"{pid} | [{agent_type}] {title[:32]} ({short_cwd}){group_badge}{is_focused}")

    if has_more:
        agent_choices.append("🌐 [Show agents from all workspaces...]")

    active_label = ws_map.get(target_ws, target_ws or "this workspace")
    prompt_text = (
        f"Select agent(s) in '{active_label}' [Tab=multi-select, Ctrl-A=all, Enter=confirm]:"
        if (allowed_ws_ids and len(active_agents) < len(sorted_agents))
        else "Select agent(s) [Tab=multi-select, Ctrl-A=all, Enter=confirm]:"
    )

    # Step 1: Select agent(s)
    selected_agent_lines = run_picker(
        prompt_text,
        agent_choices,
        multi=True,
    )
    if not selected_agent_lines:
        print("No agent selected.")
        return 0

    if any("Show agents from all workspaces" in it for it in selected_agent_lines):
        return interactive_pick_group(client, pane_id=f_pid, all_workspaces=True)

    target_pids = [
        line.split(" | ")[0].strip()
        for line in selected_agent_lines
        if "Show agents from all workspaces" not in line
    ]
    if not target_pids:
        print("No agent selected.")
        return 0

    # Step 2: Select or create task workspace
    ws_labels = [w.get("label") for w in snap.get("workspaces", []) if w.get("label")]
    clean_ws: list[str] = []
    for w in ws_labels:
        clean = re.sub(r"-agents$", "", w)
        if clean and clean not in clean_ws:
            clean_ws.append(clean)

    options: list[str] = ["➕ New task workspace..."]
    for ws in sorted(clean_ws):
        options.append(f"📁 Move to: {ws}")

    options.append("✖ Remove from group (make standalone)")
    options.append("🔄 Reset to automatic directory grouping")

    target_label = f"{len(target_pids)} agent(s)" if len(target_pids) > 1 else target_pids[0]
    prompt_label = f"Move {target_label} to task workspace:"
    chosen = run_picker(prompt_label, options, multi=False)
    if not chosen:
        print("Canceled.")
        return 0

    selected = chosen[0]

    if "Remove from group" in selected:
        for pid in target_pids:
            ungroup_agent(pid)
        apply_collapsible_groups(client, force=True)
        print(f"Removed {len(target_pids)} agent(s) from groups.")
        return 0

    if "Reset to automatic directory" in selected:
        for pid in target_pids:
            reset_agent_group(pid)
        apply_collapsible_groups(client, force=True)
        print(f"Reset {len(target_pids)} agent(s) to automatic directory grouping.")
        return 0

    target_workspace = None
    if "New task workspace" in selected:
        try:
            target_workspace = input("Enter new task workspace name: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCanceled.")
            return 0
        if not target_workspace:
            print("Workspace name cannot be empty.")
            return 1
    elif selected.startswith("📁 Move to: "):
        target_workspace = selected.split("📁 Move to: ")[1].strip()

    if target_workspace:
        ws_id = client.get_or_create_workspace(target_workspace)
        moved_count = 0
        for pid in target_pids:
            new_pid = None
            if ws_id:
                new_pid = client.move_pane_to_workspace(pid, ws_id, focus=False)
            final_pid = new_pid or pid
            move_agent_to_group(final_pid, target_workspace)
            if new_pid and new_pid != pid:
                ungroup_agent(pid)
                moved_count += 1
            elif new_pid:
                moved_count += 1
        if ws_id:
            client.focus_workspace(ws_id)
        apply_collapsible_groups(client, force=True)
        print(f"Moved {len(target_pids)} agent(s) into workspace '{target_workspace}'.")
        return 0

    clean_name = selected.strip()
    ws_id = client.get_or_create_workspace(clean_name)
    for pid in target_pids:
        new_pid = None
        if ws_id:
            new_pid = client.move_pane_to_workspace(pid, ws_id, focus=False)
        final_pid = new_pid or pid
        move_agent_to_group(final_pid, clean_name)
        if new_pid and new_pid != pid:
            ungroup_agent(pid)
    if ws_id:
        client.focus_workspace(ws_id)
    apply_collapsible_groups(client, force=True)
    print(f"Moved {len(target_pids)} agent(s) into workspace '{clean_name}'.")
    return 0


def watch(client: HerdrClient, interval: float = 2.0) -> int:
    """Daemon watching Herdr socket and keeping group badges and collapse filters active."""
    while True:
        try:
            if client.is_available():
                apply_collapsible_groups(client)
        except Exception:
            pass
        time.sleep(interval)
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for task_groups."""
    args = argv if argv is not None else sys.argv

    if "--help" in args or "-h" in args:
        print(
            "Usage: herdr-task-groups [--pick-group] [--toggle-group [NAME]]\n"
            "                        [--groups] [--collapse-all] [--expand-all]\n"
            "                        [--move-group-to-ws <GROUP> <WS>]\n"
            "                        [--ungroup] [--reset-group] [--pane PANE_ID]\n"
            "                        [--watch]"
        )
        return 0

    c = HerdrClient()

    if "--watch" in args:
        return watch(client=c)

    if "--groups" in args:
        snap = c.snapshot() if c.is_available() else {}
        groups = cluster_agents_by_group(snap)
        if not groups:
            print("No active agent task groups found.")
            return 0
        state = load_group_state()
        collapsed = set(state.get("collapsed_groups", []))
        custom_names = set(state.get("custom_groups", {}).values())
        print("Task Groups:")
        for name, agents in sorted(groups.items()):
            count = len(agents)
            is_col = name in collapsed and count > 1
            if is_col:
                title, loc = get_group_summary_info(name, agents, is_custom=(name in custom_names))
                print(f"  {title} · {loc} [COLLAPSED]")
            else:
                print(f"  ▼ {name} ({count} agents) [EXPANDED]")
        return 0

    if "--toggle-group" in args:
        idx = args.index("--toggle-group")
        group_name = None
        if idx + 1 < len(args) and not args[idx + 1].startswith("-"):
            group_name = args[idx + 1]

        snap = c.snapshot() if c.is_available() else {}
        if not group_name:
            all_groups = cluster_agents_by_group(snap)
            f_pid = snap.get("focused_pane_id")
            if f_pid:
                for g_name, g_agents in all_groups.items():
                    if any(a.get("pane_id") == f_pid for a in g_agents):
                        group_name = g_name
                        break
            if not group_name:
                multi_groups = [g for g, ag in all_groups.items() if len(ag) > 1]
                if multi_groups:
                    group_name = multi_groups[0]

        if not group_name:
            print("No active multi-agent task group to toggle.")
            return 0

        is_col = toggle_group_collapse(group_name)
        apply_collapsible_groups(c, force=True)
        status_txt = "COLLAPSED" if is_col else "EXPANDED"
        print(f"Task group '{group_name}' is now {status_txt}.")
        return 0

    if "--collapse-all" in args:
        snap = c.snapshot() if c.is_available() else {}
        groups = cluster_agents_by_group(snap)
        collapse_all_groups([g for g, ag in groups.items() if len(ag) > 1])
        apply_collapsible_groups(c, force=True)
        print("All multi-agent task groups are now COLLAPSED.")
        return 0

    if "--expand-all" in args:
        expand_all_groups()
        apply_collapsible_groups(c, force=True)
        print("All task groups are now EXPANDED.")
        return 0

    if "--toggle-scope" in args:
        scoped = toggle_workspace_scope()
        apply_collapsible_groups(c, force=True)
        status_txt = "THIS WORKSPACE ONLY" if scoped else "ALL WORKSPACES"
        print(f"Sidebar agents view scoped to: {status_txt}")
        return 0

    if "--pick-group" in args:
        pid = None
        if "--pane" in args:
            pid = args[args.index("--pane") + 1]
        all_ws = "--all" in args
        return interactive_pick_group(client=c, pane_id=pid, all_workspaces=all_ws)

    return interactive_pick_group(client=c, all_workspaces=("--all" in args))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
