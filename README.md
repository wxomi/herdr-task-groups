# Herdr Task Groups

Chrome-style task grouping, interactive `fzf` palette, and collapsible multi-agent coordination for [Herdr](https://herdr.dev).

## Why Task Groups?

When running multiple AI coding agents (Devin, Antigravity/Agy, Claude Code, Cursor) on a single task, panes and tabs quickly become cluttered. 

**Herdr Task Groups** provides:
- **Interactive `fzf` Palette (`ctrl+b alt+g`):** Quickly assign the active agent to a new or existing task group with zero manual IDs.
- **Chrome-style Collapsible Groups (`ctrl+b Shift+g`):** Collapse multiple agent tabs for a task into a single compact status indicator pill (e.g. `▶ 4 agents · auth-refactor (working)`).
- **Zero Configuration:** Automatically clusters agents by project directory and workspace by default, while letting you group them by task arbitrarily.
- **Move to Workspace:** Move an entire task group into its own dedicated Herdr workspace with one selection.

## Installation

```bash
herdr plugin install wxomi/herdr-task-groups
```

Or link locally during development:

```bash
herdr plugin link /path/to/herdr-task-groups
```

## Keybindings Setup

Add to your `~/.config/herdr/config.toml`:

```toml
[[keys.command]]
key = "prefix+t"
type = "plugin_action"
command = "wxomi.task-groups.move-to-group"
description = "open task group palette to group agent sessions"

[[keys.command]]
key = "prefix+shift+g"
type = "plugin_action"
command = "wxomi.task-groups.toggle-group"
description = "collapse or expand agent task group"
```

Then reload configuration:
```bash
herdr server reload-config
```

## CLI Usage

```bash
# Open interactive fzf group palette
./run.sh --pick-group

# Toggle collapse state for the focused task group
./run.sh --toggle-group

# List all task groups and agents
./run.sh --groups

# Collapse or expand all groups
./run.sh --collapse-all
./run.sh --expand-all
```

## License

MIT
