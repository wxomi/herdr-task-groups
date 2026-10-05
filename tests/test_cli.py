"""Unit tests for interactive_pick_group workspace scoping."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from task_groups.cli import interactive_pick_group


class TestCliWorkspaceScoping(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_client = MagicMock()
        self.mock_client.is_available.return_value = True
        self.mock_client.snapshot.return_value = {
            "workspaces": [
                {"workspace_id": "w8", "label": "devel-agents"},
                {"workspace_id": "wE", "label": "devel"},
                {"workspace_id": "wH", "label": "Hirebase"},
                {"workspace_id": "wN", "label": "Prod Monitoring"},
            ],
            "agents": [
                {"pane_id": "w8:p1", "workspace_id": "w8", "title": "devel agent 1"},
                {"pane_id": "w8:p2", "workspace_id": "w8", "title": "devel agent 2"},
                {"pane_id": "wH:p1", "workspace_id": "wH", "title": "hirebase agent"},
                {"pane_id": "wN:p1", "workspace_id": "wN", "title": "prod agent"},
            ],
        }

    @patch("task_groups.cli.run_picker")
    def test_pick_group_scopes_to_active_workspace(self, mock_picker: MagicMock) -> None:
        mock_picker.return_value = []
        with patch.dict("os.environ", {"TARGET_WORKSPACE": "wH"}):
            interactive_pick_group(self.mock_client)
            mock_picker.assert_called_once()
            prompt, items = mock_picker.call_args[0][:2]
            self.assertIn("Hirebase", prompt)
            # Only Hirebase agent + show all option
            agent_items = [it for it in items if "Show agents from all workspaces" not in it]
            self.assertEqual(len(agent_items), 1)
            self.assertTrue(agent_items[0].startswith("wH:p1"))

    @patch("task_groups.cli.run_picker")
    def test_pick_group_devel_agents_scoping(self, mock_picker: MagicMock) -> None:
        mock_picker.return_value = []
        with patch.dict("os.environ", {"TARGET_WORKSPACE": "w8"}):
            interactive_pick_group(self.mock_client)
            mock_picker.assert_called_once()
            _, items = mock_picker.call_args[0][:2]
            agent_items = [it for it in items if "Show agents from all workspaces" not in it]
            self.assertEqual(len(agent_items), 2)
            self.assertTrue(all("w8:" in it for it in agent_items))

    @patch("task_groups.cli.run_picker")
    def test_pick_group_all_workspaces(self, mock_picker: MagicMock) -> None:
        mock_picker.return_value = []
        interactive_pick_group(self.mock_client, all_workspaces=True)
        mock_picker.assert_called_once()
        _, items = mock_picker.call_args[0][:2]
        self.assertEqual(len(items), 4)


if __name__ == "__main__":
    unittest.main()
