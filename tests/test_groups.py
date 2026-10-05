"""Unit tests for task groups, clustering, and summary pill generation."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from task_groups.groups import (
    clean_agent_title,
    cluster_agents_by_group,
    extract_common_task_topic,
    get_canonical_group_name,
    get_group_summary_info,
    is_group_collapsed,
    load_group_state,
    move_agent_to_group,
    reset_agent_group,
    save_group_state,
    toggle_group_collapse,
    ungroup_agent,
)


class TestTaskGroups(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = os.path.join(self.temp_dir.name, "group_state.json")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_canonical_group_name(self) -> None:
        self.assertEqual(get_canonical_group_name("devel"), "devel")
        self.assertEqual(get_canonical_group_name("devel-agents"), "devel")
        self.assertEqual(get_canonical_group_name("auction-agents"), "auction")
        self.assertEqual(get_canonical_group_name("~-agents"), "~")
        self.assertEqual(get_canonical_group_name("~"), "~")
        self.assertEqual(get_canonical_group_name(""), "")

    def test_cluster_agents_by_group(self) -> None:
        snap = {
            "workspaces": [
                {"workspace_id": "w1", "label": "devel"},
                {"workspace_id": "w2", "label": "devel-agents"},
                {"workspace_id": "w3", "label": "auction"},
            ],
            "agents": [
                {"pane_id": "p1", "workspace_id": "w1", "title": "Map T45399"},
                {"pane_id": "p2", "workspace_id": "w2", "title": "batched alert"},
                {"pane_id": "p3", "workspace_id": "w3", "title": "Job not found"},
            ],
        }
        groups = cluster_agents_by_group(snap)
        self.assertIn("devel", groups)
        self.assertIn("auction", groups)
        self.assertEqual(len(groups["devel"]), 2)
        self.assertEqual(len(groups["auction"]), 1)

    def test_group_summary_info(self) -> None:
        agents = [
            {"pane_id": "p1", "agent_status": "working", "tokens": {"session": "Task T45399"}},
            {"pane_id": "p2", "agent_status": "idle", "tokens": {"session": "Task T45399"}},
            {"pane_id": "p3", "agent_status": "idle", "tokens": {"session": "Task T45399"}},
        ]
        title, location = get_group_summary_info("devel", agents)
        self.assertIn("3 agents", title)
        self.assertIn("1 working, 2 idle", location)

    def test_clean_agent_title(self) -> None:
        self.assertEqual(clean_agent_title("▶ Map T45399 (3 agents)"), "Map T45399")
        self.assertEqual(clean_agent_title("▼ devel · Fix Auth (2 agents)"), "Fix Auth")
        self.assertEqual(clean_agent_title("Normal Title"), "Normal Title")

    def test_extract_common_task_topic(self) -> None:
        agents = [
            {"pane_id": "p1", "tokens": {"session": "Fix T45399 crash"}},
            {"pane_id": "p2", "tokens": {"session": "Review T45399 diff"}},
        ]
        topic = extract_common_task_topic(agents)
        self.assertEqual(topic, "Task T45399")

    def test_load_and_save_group_state(self) -> None:
        with patch("task_groups.groups.GROUP_STATE_FILE", self.state_file):
            state = {"collapsed_groups": ["devel"], "custom_groups": {"p1": "task-x"}, "ungrouped_panes": []}
            save_group_state(state)
            loaded = load_group_state()
            self.assertEqual(loaded["collapsed_groups"], ["devel"])
            self.assertEqual(loaded["custom_groups"], {"p1": "task-x"})

    def test_toggle_group_collapse(self) -> None:
        with patch("task_groups.groups.GROUP_STATE_FILE", self.state_file):
            self.assertFalse(is_group_collapsed("devel"))
            is_col = toggle_group_collapse("devel")
            self.assertTrue(is_col)
            self.assertTrue(is_group_collapsed("devel"))
            is_col2 = toggle_group_collapse("devel")
            self.assertFalse(is_col2)
            self.assertFalse(is_group_collapsed("devel"))

    def test_move_agent_to_group(self) -> None:
        with patch("task_groups.groups.GROUP_STATE_FILE", self.state_file):
            move_agent_to_group("p1", "my-task")
            loaded = load_group_state()
            self.assertEqual(loaded["custom_groups"].get("p1"), "my-task")
            self.assertNotIn("p1", loaded["ungrouped_panes"])

            ungroup_agent("p1")
            loaded2 = load_group_state()
            self.assertNotIn("p1", loaded2["custom_groups"])
            self.assertIn("p1", loaded2["ungrouped_panes"])

            reset_agent_group("p1")
            loaded3 = load_group_state()
            self.assertNotIn("p1", loaded3["custom_groups"])
            self.assertNotIn("p1", loaded3["ungrouped_panes"])


if __name__ == "__main__":
    unittest.main()
