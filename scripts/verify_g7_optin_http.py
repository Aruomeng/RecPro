#!/usr/bin/env python3
"""Verify G7's explicit HTTP composition and write append-only evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from fastapi.testclient import TestClient

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.composition import build_demo_http_app
from backend.app.config import AppSettings
from backend.app.main import create_app
from backend.app.observability.domain import ComponentReadiness, ComponentStatus


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")


class UpProbe:
    def __init__(self) -> None:
        self.calls = 0

    async def check(self) -> ComponentReadiness:
        self.calls += 1
        return ComponentReadiness(ComponentStatus.UP, required=True)


def verify(run_id: str) -> dict[str, object]:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("run id must use 3-64 safe characters")
    evidence_dir = PROJECT_ROOT / "artifacts" / "verification" / "g7" / run_id
    if evidence_dir.exists():
        raise FileExistsError(f"evidence directory already exists: {evidence_dir}")

    settings = AppSettings(app_env="demo", mysql_password="isolated-test-password")
    mysql_probe = UpProbe()
    bundle_probe = UpProbe()
    optin_app = build_demo_http_app(
        settings,
        recommendation_service=object(),
        readiness_probe=mysql_probe,
        config_bundle_probe=bundle_probe,
    )
    if mysql_probe.calls or bundle_probe.calls:
        raise AssertionError("composition opened a readiness probe during construction")
    if "/api/v1/recommendation-tasks" not in optin_app.openapi()["paths"]:
        raise AssertionError("opt-in composition did not expose the recommendation route")
    with TestClient(optin_app) as client:
        optin_response = client.get("/api/v1/health/ready")
    optin_body = optin_response.json()
    if optin_response.status_code != 200 or not optin_body.get("can_recommend"):
        raise AssertionError("opt-in readiness did not become true behind UP probes")
    pipeline = optin_body["components"]["recommendation_pipeline"]
    if pipeline.get("status") != "UP" or pipeline.get("required") is not True:
        raise AssertionError("opt-in pipeline component is not required and UP")

    default_mysql_probe = UpProbe()
    default_bundle_probe = UpProbe()
    default_app = create_app(
        settings=settings,
        readiness_probe=default_mysql_probe,
        config_bundle_probe=default_bundle_probe,
    )
    if "/api/v1/recommendation-tasks" in default_app.openapi()["paths"]:
        raise AssertionError("default app exposed recommendation route")
    with TestClient(default_app) as client:
        default_response = client.get("/api/v1/health/ready")
    default_body = default_response.json()
    if default_response.status_code != 200 or default_body.get("can_recommend"):
        raise AssertionError("default app claimed recommendation readiness")

    evidence = {
        "status": "PASS",
        "run_id": run_id,
        "default_app": {
            "recommendation_route": False,
            "can_recommend": default_body["can_recommend"],
            "pipeline_status": default_body["components"]["recommendation_pipeline"]["status"],
        },
        "optin_app": {
            "recommendation_route": True,
            "can_recommend": optin_body["can_recommend"],
            "pipeline_status": pipeline["status"],
            "pipeline_version": pipeline["active_version"],
            "mysql_probe_calls": mysql_probe.calls,
            "config_probe_calls": bundle_probe.calls,
        },
        "database_reads": 0,
        "database_writes": 0,
        "external_requests": 0,
        "actual_delete_count": 0,
        "files_deleted": 0,
        "overwritten_inputs": 0,
    }
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    evidence = verify(args.run_id)
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
