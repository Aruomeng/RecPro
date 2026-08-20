from __future__ import annotations

import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.agent_workspace import AgentWorkspaceBroker
from backend.app.config import AppSettings
from backend.app.main import create_app


class AgentWorkspaceAPITests(unittest.TestCase):
    def app(self, *, enabled: bool):
        return create_app(
            settings=AppSettings(app_env="demo", mysql_password="isolated-test-password"),
            agent_workspace_broker=AgentWorkspaceBroker() if enabled else None,
        )

    def test_default_app_does_not_mount_workspace(self) -> None:
        self.assertNotIn("/api/v1/agent-workspaces", self.app(enabled=False).openapi()["paths"])

    def test_opt_in_workspace_supports_snapshot_observation_and_catalog(self) -> None:
        with TestClient(self.app(enabled=True)) as client:
            session_id = str(uuid4())
            created = client.post(
                "/api/v1/agent-workspaces",
                headers={"X-Demo-User-Id": "9000001"},
                json={"session_id": session_id, "mode": "guest"},
            )
            self.assertEqual(202, created.status_code, created.text)
            body = created.json()
            self.assertEqual(8, len(body["workspace"]["agents"]))
            workspace_id = body["workspace"]["workspace_id"]
            observation_id = str(uuid4())
            observed = client.post(
                f"/api/v1/agent-workspaces/{workspace_id}/observations",
                headers={"X-Demo-User-Id": "9000001", "Idempotency-Key": observation_id},
                json={"observation_id": observation_id, "event_type": "GRAPH_NODE_SELECTED", "payload": {"entity_id": "topic:1", "label": "多智能体"}},
            )
            self.assertEqual(202, observed.status_code, observed.text)
            self.assertTrue(any(item["type"] == "SUGGEST_NEXT_ACTION" for item in observed.json()["workspace"]["directives"]))
            catalog = client.get("/api/v1/agents")
            self.assertEqual(8, len(catalog.json()["agents"]))

    def test_identity_cannot_read_another_workspace(self) -> None:
        with TestClient(self.app(enabled=True)) as client:
            created = client.post(
                "/api/v1/agent-workspaces",
                headers={"X-Demo-User-Id": "9000001"},
                json={"session_id": str(uuid4()), "mode": "guest"},
            ).json()
            response = client.get(
                f"/api/v1/agent-workspaces/{created['workspace']['workspace_id']}",
                headers={"X-Demo-User-Id": "1001"},
            )
            self.assertEqual(404, response.status_code)


if __name__ == "__main__":
    unittest.main()
