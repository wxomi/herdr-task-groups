"""CLI entrypoint and interactive multi-select fzf palette for Herdr Task Groups."""

from __future__ import annotations

import os
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
    move_agent_to_group,
    move_group_to_workspace,
    reset_agent_group,
    toggle_group_collapse,
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


def interactive_pick_group(client: HerdrClient, pane_id: str | None = None) -> int:
    """Interactively select one or multiple agents and move them to a task group."""
    snap = client.snapshot() if client.is_available() else {}
    agents = snap.get("agents", [])
    if not agents:
        print("No active agents found in Herdr.")
        return 1

    state = load_group_state()
    custom_groups = state.get("custom_groups", {})
    all_groups = cluster_agents_by_group(snap)

    f_pid = pane_id or os.environ.get("TARGET_PANE") or snap.get("focused_pane_id")

    # Sort agents: focused pane first
    sorted_agents = sorted(
        agents,
        key=lambda a: (0 if a.get("pane_id") == f_pid else 1, a.get("pane_id", ""))
    )

    agent_choices = []
    for a in sorted_agents:
        pid = a.get("pane_id", "")
        agent_type = a.get("agent", "agent")
        title = (a.get("tokens") or {}).get("session") or a.get("title", "")
        cwd = a.get("cwd", "")
        short_cwd = cwd.split("/")[-1] if cwd else "~"
        current_g = custom_groups.get(pid)
        group_badge = f" [Group: {current_g}]" if current_g else ""
        is_focused = " (focused)" if pid == f_pid else ""
        agent_choices.append(f"{pid} | [{agent_type}] {title[:32]} ({short_cwd}){group_badge}{is_focused}")

    # Prompt user to select agent(s) (Tab to mark multiple, Enter to confirm)
    selected_agent_lines = run_picker(
        "Select agent(s) [Tab=multi-select, Ctrl-A=all, Enter=confirm]:",
        agent_choices,
        multi=True,
    )
    if not selected_agent_lines:
        print("No agent selected.")
        return 0

    target_pids = [line.split(" | ")[0].strip() for line in selected_agent_lines]

    # Present group options
    existing_groups = sorted([g for g in all_groups if not g.startswith("_solo_")])
    options: list[str] = []
    for g in existing_groups:
        options.append(f"📁 Move to: {g}")

    options.append("➕ New group...")
    options.append("✖ Remove from group (make standalone)")
    options.append("🔄 Reset to automatic directory grouping")
    if len(target_pids) == 1:
        curr_g = custom_groups.get(target_pids[0])
        if curr_g and not curr_g.startswith("_solo_"):
            options.append(f"📦 Move entire group '{curr_g}' to workspace...")

    target_label = f"{len(target_pids)} agent(s)" if len(target_pids) > 1 else target_pids[0]
    prompt_label = f"Move {target_label} to group:"
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

    if "Move entire group" in selected:
        curr_g = custom_groups.get(target_pids[0])
        if curr_g:
            ws_options = [w.get("label") or w.get("workspace_id", "") for w in snap.get("workspaces", [])]
            ws_options.append("➕ New workspace...")
            chosen_ws = run_picker(f"Move group '{curr_g}' to workspace:", ws_options, multi=False)
            if not chosen_ws:
                print("Canceled.")
                return 0
            if "New workspace" in chosen_ws[0]:
                target_ws = input("Enter new workspace name: ").strip()
            else:
                target_ws = chosen_ws[0]
            if target_ws:
                count = move_group_to_workspace(client, curr_g, target_ws)
                apply_collapsible_groups(client, force=True)
                print(f"Moved {count} agents in group '{curr_g}' to workspace '{target_ws}'.")
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
        for pid in target_pids:
            move_agent_to_group(pid, new_group)
        apply_collapsible_groups(client, force=True)
        print(f"Moved {len(target_pids)} agent(s) to new group '{new_group}'.")
        return 0

    if selected.startswith("📁 Move to: "):
        g_name = selected.split("📁 Move to: ")[1].strip()
        for pid in target_pids:
            move_agent_to_group(pid, g_name)
        apply_collapsible_groups(client, force=True)
        print(f"Moved {len(target_pids)} agent(s) to group '{g_name}'.")
        return 0

    clean_name = selected.strip()
    for pid in target_pids:
        move_agent_to_group(pid, clean_name)
    apply_collapsible_groups(client, force=True)
    print(f"Moved {len(target_pids)} agent(s) to group '{clean_name}'.")
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

    if "--pick-group" in args:
        pid = None
        if "--pane" in args:
            pid = args[args.index("--pane") + 1]
        return interactive_pick_group(client=c, pane_id=pid)

    return interactive_pick_group(client=c)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
