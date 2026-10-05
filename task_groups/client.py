"""Direct Unix domain socket client for Herdr JSON-RPC."""

from __future__ import annotations

import json
import os
import socket

from task_groups.config import HERDR_SOCKET_PATH


class HerdrClient:
    """Direct Unix domain socket client for Herdr JSON-RPC."""

    def __init__(self, sock_path: str | None = None):
        self.sock_path = sock_path or HERDR_SOCKET_PATH
        self._new_workspace_initial_tabs: dict[str, str] = {}

    def is_available(self) -> bool:
        return bool(self.sock_path and os.path.exists(self.sock_path))

    def call(self, method: str, params: dict | None = None, req_id: str = "p") -> dict:
        if not self.is_available():
            return {}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect(self.sock_path)
                payload = (
                    json.dumps({"id": req_id, "method": method, "params": params or {}})
                    + "\n"
                )
                s.sendall(payload.encode("utf-8"))
                buf = b""
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                    if b"\n" in chunk:
                        break
                    if not buf:
                        return {}
                return json.loads(buf.decode("utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def snapshot(self) -> dict:
        res = self.call("session.snapshot")
        return (res.get("result") or {}).get("snapshot") or {}

    def report_metadata(
        self,
        pane_id: str,
        source: str,
        tokens: dict[str, str | None],
        title: str | None = None,
        display_agent: str | None = None,
    ) -> bool:
        params: dict = {"pane_id": pane_id, "source": source, "tokens": tokens}
        if title:
            params["title"] = title
        if display_agent:
            params["display_agent"] = display_agent
        res = self.call("pane.report_metadata", params)
        return "result" in res

    def close_tab(self, tab_id: str) -> bool:
        res = self.call("tab.close", {"tab_id": tab_id})
        return "result" in res

    def focus_workspace(self, workspace_id: str) -> bool:
        res = self.call("workspace.focus", {"workspace_id": workspace_id})
        return "result" in res

    def focus_tab(self, tab_id: str) -> bool:
        res = self.call("tab.focus", {"tab_id": tab_id})
        return "result" in res

    def move_pane_to_workspace(
        self, pane_id: str, workspace_id: str, focus: bool = False
    ) -> str | None:
        res = self.call(
            "pane.move",
            {
                "pane_id": pane_id,
                "destination": {"type": "new_tab", "workspace_id": workspace_id},
                "focus": focus,
            },
        )
        ok = "result" in res
        if ok:
            init_tab = self._new_workspace_initial_tabs.pop(workspace_id, None)
            if init_tab:
                self.close_tab(init_tab)
            move_res = (res.get("result") or {}).get("move_result") or {}
            created_tab = move_res.get("created_tab") or {}
            new_tab_id = created_tab.get("tab_id")
            new_pane_id = (
                (move_res.get("pane") or {}).get("pane_id")
                or move_res.get("focused_pane_id")
                or pane_id
            )
            if focus:
                self.focus_workspace(workspace_id)
                if new_tab_id:
                    self.focus_tab(new_tab_id)
            return new_pane_id
        return None

    def get_or_create_workspace(self, name: str) -> str | None:
        res = self.call("workspace.list")
        workspaces = (res.get("result") or {}).get("workspaces") or []
        for ws in workspaces:
            if (ws.get("label") or "").lower() == name.lower():
                return ws.get("workspace_id")
        created = self.call("workspace.create", {"label": name, "no_focus": True})
        ws_info = (created.get("result") or {}).get("workspace") or {}
        ws_id = ws_info.get("workspace_id")
        if ws_id:
            tab_info = (created.get("result") or {}).get("tab") or {}
            init_tab = tab_info.get("tab_id") or ws_info.get("active_tab_id")
            if init_tab:
                self._new_workspace_initial_tabs[ws_id] = init_tab
        return ws_id

    def set_agent_view(self, source: str, label: str, filter_dict: dict) -> bool:
        res = self.call(
            "agent.view.set",
            {"source": source, "label": label, "filter": filter_dict},
        )
        return "result" in res

    def clear_agent_view(self, source: str) -> bool:
        res = self.call("agent.view.clear", {"source": source})
        return "result" in res
