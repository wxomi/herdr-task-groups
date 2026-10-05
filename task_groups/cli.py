"""CLI entrypoint and interactive fzf palette for Herdr Task Groups."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from task_groups.client import HerdrClient
from task_groups.groups import (
    apply_collapsible_groups,
    cluster_agents_by_group,
    collapse_all_groups,
    expand_all_groups,
    get_group_summary_info,
    load_group_state,
    move_agent_to_group,
    move_group_to_workspace,
    reset_agent_group,
    toggle_group_collapse,
    ungroup_agent,
)


def run_picker(prompt: str, items: list[str]) -> str | None:
    """Show an interactive selection menu using fzf if available, else numeric stdin prompt."""
    fzf_bin = shutil.which("fzf") or (
        "/opt/homebrew/bin/fzf" if os.path.exists("/opt/homebrew/bin/fzf") else None
    )

    if fzf_bin and sys.stdin.isatty():
        try:
            proc = subprocess.Popen(
                [
                    fzf_bin,
                    "--prompt",
                    f"{prompt} > ",
                    "--height",
                    "40%",
                    "--layout=reverse",
                    "--border",
                    "--cycle",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
            )
            out, _ = proc.communicate(input="\n".join(items) + "\n")
            if proc.returncode == 0 and out.strip():
                return out.strip()
            return None
        except Exception:
            pass

    print(f"\n{prompt}")
    for idx, it in enumerate(items, 1):
        print(f"  [{idx}] {it}")
    print("  [q] Cancel\n")
    try:
        choice = input("Enter selection: ").strip()
        if not choice or choice.lower() == "q":
            return None
        if choice.isdigit():
            num = int(choice)
            if 1 <= num <= len(items):
                return items[num - 1]
        for it in items:
            if choice.lower() in it.lower():
                return it
    except (EOFError, KeyboardInterrupt):
        return None
    return None


def interactive_pick_group(client: HerdrClient, pane_id: str | None = None) -> int:
    """Interactively move an agent to an existing, new, or ungrouped task group."""
    snap = client.snapshot() if client.is_available() else {}
    agents = snap.get("agents", [])
    if not agents:
        print("No active agents found in Herdr.")
        return 1

    agents_by_pane = {a.get("pane_id"): a for a in agents if a.get("pane_id")}

    target_pid = (
        pane_id
        or os.environ.get("TARGET_PANE")
        or os.environ.get("HERDR_PANE_ID")
    )

    if not target_pid or target_pid not in agents_by_pane:
        f_pid = snap.get("focused_pane_id")
        if f_pid and f_pid in agents_by_pane:
            target_pid = f_pid

    if not target_pid or target_pid not in agents_by_pane:
        if len(agents) == 1:
            target_pid = agents[0].get("pane_id")
        else:
            agent_choices = []
            for a in agents:
                pid = a.get("pane_id", "")
                agent_type = a.get("agent", "agent")
                title = (a.get("tokens") or {}).get("session") or a.get("title", "")
                cwd = a.get("cwd", "")
                short_cwd = cwd.split("/")[-1] if cwd else "~"
                agent_choices.append(f"{pid} | [{agent_type}] {title} ({short_cwd})")

            chosen = run_picker("Select agent to move:", agent_choices)
            if not chosen:
                print("No agent selected.")
                return 0
            target_pid = chosen.split(" | ")[0].strip()

    target_agent = agents_by_pane.get(target_pid, {})
    agent_name = target_agent.get("agent", "agent")
    agent_title = (target_agent.get("tokens") or {}).get("session") or target_agent.get("title", "")

    state = load_group_state()
    ungrouped_panes = set(state.get("ungrouped_panes", []))
    all_groups = cluster_agents_by_group(snap)

    current_group = None
    for g_name, g_agents in all_groups.items():
        if any(a.get("pane_id") == target_pid for a in g_agents):
            current_group = g_name
            break
    if not current_group:
        current_group = "default"

    is_ungrouped = target_pid in ungrouped_panes

    options: list[str] = []

    # 1. Existing groups
    existing_groups = sorted([g for g in all_groups if not g.startswith("_solo_")])
    for g in existing_groups:
        if g == current_group and not is_ungrouped:
            options.append(f"📁 Move to: {g}  (current)")
        else:
            options.append(f"📁 Move to: {g}")

    # 2. Group actions
    options.append("➕ New group...")
    options.append("✖ Remove from group (make standalone)")
    options.append("🔄 Reset to automatic directory grouping")
    if current_group and not current_group.startswith("_solo_"):
        options.append(f"📦 Move entire group '{current_group}' to workspace...")

    prompt_label = f"Agent: [{agent_name}] {agent_title[:28]}"
    if is_ungrouped:
        prompt_label += " [Ungrouped]"
    elif current_group:
        prompt_label += f" [Group: {current_group}]"

    selected = run_picker(prompt_label, options)
    if not selected:
        print("Canceled.")
        return 0

    if "Remove from group" in selected:
        ungroup_agent(target_pid)
        apply_collapsible_groups(client, force=True)
        print(f"Agent {target_pid} removed from group (now standalone).")
        return 0

    if "Reset to automatic directory" in selected:
        reset_agent_group(target_pid)
        apply_collapsible_groups(client, force=True)
        print(f"Agent {target_pid} reset to automatic directory grouping.")
        return 0

    if "Move entire group" in selected:
        ws_options = [w.get("label") or w.get("workspace_id", "") for w in snap.get("workspaces", [])]
        ws_options.append("➕ New workspace...")
        chosen_ws = run_picker(f"Move group '{current_group}' to workspace:", ws_options)
        if not chosen_ws:
            print("Canceled.")
            return 0
        if "New workspace" in chosen_ws:
            target_ws = input("Enter new workspace name: ").strip()
        else:
            target_ws = chosen_ws
        if target_ws:
            count = move_group_to_workspace(client, current_group, target_ws)
            apply_collapsible_groups(client, force=True)
            print(f"Moved {count} agents in group '{current_group}' to workspace '{target_ws}'.")
        return 0

    if "New group..." in selected:
        try:
            new_group = input("Enter new group name: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCanceled.")
            return 0
        if not new_group:
            print("Group name cannot be empty.")
            return 1
        move_agent_to_group(target_pid, new_group)
        apply_collapsible_groups(client, force=True)
        print(f"Moved agent {target_pid} to new group '{new_group}'.")
        return 0

    if selected.startswith("📁 Move to: "):
        g_name = selected.split("📁 Move to: ")[1].split("  (current)")[0].strip()
        move_agent_to_group(target_pid, g_name)
        apply_collapsible_groups(client, force=True)
        print(f"Moved agent {target_pid} to group '{g_name}'.")
        return 0

    clean_name = selected.strip()
    move_agent_to_group(target_pid, clean_name)
    apply_collapsible_groups(client, force=True)
    print(f"Moved agent {target_pid} to group '{clean_name}'.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for task_groups."""
    args = argv if argv is not None else sys.argv

    if "--help" in args or "-h" in args:
        print(
            "Usage: herdr-task-groups [--pick-group] [--toggle-group [NAME]]\n"
            "                        [--groups] [--collapse-all] [--expand-all]\n"
            "                        [--move-group-to-ws <GROUP> <WS>]\n"
            "                        [--ungroup] [--reset-group] [--pane PANE_ID]"
        )
        return 0

    c = HerdrClient()

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

    if "--pick-group" in args:
        pid = None
        if "--pane" in args:
            pid = args[args.index("--pane") + 1]
        return interactive_pick_group(client=c, pane_id=pid)

    # Default action if no flag is passed: pick-group
    return interactive_pick_group(client=c)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
