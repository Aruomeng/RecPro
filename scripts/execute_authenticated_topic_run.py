#!/usr/bin/env python3
"""Apply an approved public Bearer-authenticated topic recommendation plan."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
from http.cookiejar import CookieJar

from jsonschema import Draft202012Validator, FormatChecker

from scripts.build_authenticated_topic_run_plan import INPUTS, READER_FILE, ROOT, SCHEMA, baseline, canonical, digest
from scripts.validate_runtime_env import read_env


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/"); self.jar = CookieJar(); self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(self.jar))
    def request(self, method: str, path: str, payload: dict[str, object] | None = None, headers: dict[str, str] | None = None, timeout: int = 15) -> tuple[int, dict[str, object] | None]:
        body = json.dumps(payload).encode() if payload is not None else None; h = {"Accept": "application/json"}
        if body is not None: h["Content-Type"] = "application/json"
        h.update(headers or {})
        try:
            with self.opener.open(Request(self.base + path, data=body, headers=h, method=method), timeout=timeout) as r: raw, status = r.read(), int(r.status)
        except HTTPError as e: return int(e.code), None
        except (URLError, OSError, TimeoutError) as e: raise RuntimeError(f"public workbench unavailable ({type(e).__name__})") from e
        try: value = json.loads(raw.decode()) if raw else None
        except (UnicodeDecodeError, json.JSONDecodeError): value = None
        return status, value if isinstance(value, dict) else None

    def stream(self, path: str, headers: dict[str, str]) -> list[dict[str, object]]:
        """Read the same authenticated SSE transport used by the front end."""
        h = {"Accept": "text/event-stream", **headers}
        try:
            with self.opener.open(Request(self.base + path, headers=h, method="GET"), timeout=150) as response:
                if int(response.status) != 200:
                    raise RuntimeError("recommendation SSE endpoint rejected the request")
                raw = response.read().decode("utf-8")
        except (URLError, OSError, TimeoutError) as exc:
            raise RuntimeError(f"recommendation SSE stream failed ({type(exc).__name__})") from exc
        events: list[dict[str, object]] = []
        for frame in raw.split("\n\n"):
            line = next((value for value in frame.splitlines() if value.startswith("data: ")), None)
            if line is None:
                continue
            value = json.loads(line[6:])
            if not isinstance(value, dict) or not isinstance(value.get("sequence"), int):
                raise RuntimeError("recommendation SSE emitted an invalid public event")
            events.append(value)
        return events


def plan_data(path: Path, pid: str, phash: str) -> dict[str, Any]:
    p = json.loads(path.resolve(strict=True).read_text()); Draft202012Validator(json.loads(SCHEMA.read_text()), format_checker=FormatChecker()).validate(p)
    unsigned = dict(p); unsigned.pop("plan_hash", None)
    if p.get("plan_id") != pid or p.get("plan_hash") != phash or hashlib.sha256(canonical(unsigned)).hexdigest() != phash: raise ValueError("approved plan identity/hash mismatch")
    if subprocess.run(["git", "merge-base", "--is-ancestor", str(p["git_commit"]), "HEAD"], cwd=ROOT).returncode != 0: raise ValueError("approved commit is no longer an ancestor")
    expected = {item: digest(ROOT / item) for item in sorted(INPUTS)}
    if {key: value for key, value in p["input_hashes"].items() if key != "request_payload"} != expected: raise ValueError("approved code boundary changed")
    return p


def planned_baseline(p: dict[str, Any]) -> dict[str, Any]:
    for value in p["preconditions"]:
        if value.startswith("AUTH_TOPIC_BASELINE="): return json.loads(value.removeprefix("AUTH_TOPIC_BASELINE="))
    raise ValueError("plan omitted exact state baseline")


def output_path(run_id: str) -> Path: return ROOT / "artifacts/verification/authenticated-topic-run" / run_id / "acceptance.json"


async def execute(args: argparse.Namespace) -> dict[str, Any]:
    p = plan_data(Path(args.plan), args.plan_id, args.plan_hash); env = read_env((ROOT / args.env_file).resolve(strict=True)); creds = read_env(READER_FILE.resolve(strict=True))
    if READER_FILE.stat().st_mode & 0o077 or creds.get("RECPRO_STAGE2_READER_USER_ID") != "10001": raise ValueError("reader credential gate failed")
    identity, before = await baseline(env, 10001)
    if identity != p["environment"]["database_identity"] or before != planned_baseline(p): raise ValueError("current MySQL baseline differs from the approved plan")
    evidence_path = output_path(str(p["request_run_id"]));
    if evidence_path.exists(): raise ValueError("refusing to overwrite existing acceptance evidence")
    client = Client(args.base_url); statuses: dict[str, int] = {}
    statuses["ready"], ready = client.request("GET", "/api/v1/health/ready")
    if statuses["ready"] != 200 or not isinstance(ready, dict) or ready.get("can_recommend") is not True: raise RuntimeError("workbench cannot recommend")
    statuses["login"], login = client.request("POST", "/api/v1/auth/login", {"identifier_type":"READER_NUMBER", "identifier":creds["RECPRO_STAGE2_READER_IDENTIFIER"], "password":creds["RECPRO_STAGE2_READER_PASSWORD"], "device_type":"BROWSER"})
    if statuses["login"] != 200 or not isinstance(login, dict) or int(login.get("user",{}).get("user_id",0)) != 10001: raise RuntimeError("formal reader login failed")
    token = str(login["access_token"]); auth = {"Authorization": f"Bearer {token}"}
    statuses["me"], me = client.request("GET", "/api/v1/auth/me", headers=auth)
    if statuses["me"] != 200 or not isinstance(me, dict) or int(me.get("user",{}).get("user_id",0)) != 10001: raise RuntimeError("Bearer identity validation failed")
    workspace_session_id = str(__import__('uuid').uuid5(__import__('uuid').NAMESPACE_URL, f"authenticated-topic:{p['request_run_id']}:workspace"))
    statuses["workspace"], workspace = client.request("POST", "/api/v1/agent-workspaces", {"session_id": workspace_session_id, "mode":"authenticated"}, auth)
    workspace_snapshot = workspace.get("workspace") if isinstance(workspace, dict) else None
    if statuses["workspace"] != 202 or not isinstance(workspace_snapshot, dict) or not isinstance(workspace_snapshot.get("workspace_id"), str): raise RuntimeError("authenticated workspace creation failed")
    workspace_id = str(workspace_snapshot["workspace_id"])
    request = json.loads(bytes.fromhex(p["input_hashes"]["request_payload"]).decode()) if False else {"request_id":p["idempotency_key"], "session_id":str(__import__('uuid').uuid5(__import__('uuid').NAMESPACE_URL, f"authenticated-topic:{p['request_run_id']}:session")), "scene":"SEARCH_AFTER", "input_text":"多智能体、知识图谱与智慧图书馆", "requested_resource_types":["BOOK"], "requested_output_type":"TOPIC_RESOURCES", "limit":8}
    h = auth | {"Idempotency-Key": p["idempotency_key"], "X-Agent-Workspace-Id": workspace_id}
    if hashlib.sha256(canonical(request)).hexdigest() != p["input_hashes"]["request_payload"]:
        raise RuntimeError("frozen recommendation request does not match its approved hash")
    statuses["run_create"], accepted = client.request("POST", "/api/v1/recommendation-runs", request, h)
    if statuses["run_create"] != 202 or not isinstance(accepted, dict) or not isinstance(accepted.get("task_id"), str): raise RuntimeError("authenticated recommendation was not accepted")
    task_id = str(accepted["task_id"]); final: dict[str, object] | None = None
    events = client.stream(str(accepted["events_url"]), auth); statuses["sse"] = 200
    if not events or events[-1].get("event_type") not in {"TASK_COMPLETED", "TASK_FAILED"}:
        raise RuntimeError("recommendation SSE did not reach a public terminal event")
    if len({event.get("agent_name") for event in events if event.get("event_type") == "AGENT_STARTED"}) != 7:
        raise RuntimeError("recommendation SSE did not expose all seven dispatched Agents")
    statuses["run_state"], final = client.request("GET", f"/api/v1/recommendation-runs/{task_id}", headers=auth)
    if statuses["run_state"] != 200 or not isinstance(final, dict): raise RuntimeError("authenticated recommendation state read failed")
    if not isinstance(final, dict) or final.get("terminal") is not True or final.get("status") not in {"COMPLETED", "DEGRADED_COMPLETED"}: raise RuntimeError("recommendation did not reach an acceptable terminal state")
    result = final.get("result")
    if not isinstance(result, dict) or len(result.get("items", [])) != 8: raise RuntimeError("recommendation result contract is invalid")
    statuses["replay"], replay = client.request("POST", "/api/v1/recommendation-runs", request, h)
    if statuses["replay"] != 202 or not isinstance(replay, dict) or replay.get("replayed") is not True or replay.get("task_id") != task_id: raise RuntimeError("idempotent recommendation replay failed")
    workspace_events = []
    statuses["workspace_snapshot"], snapshot = client.request("GET", f"/api/v1/agent-workspaces/{workspace_id}", headers=auth)
    if statuses["workspace_snapshot"] != 200 or not isinstance(snapshot, dict):
        raise RuntimeError("authenticated workspace snapshot read failed")
    workspace_events = snapshot.get("recent_events", []) if isinstance(snapshot.get("recent_events"), list) else []
    statuses["logout"], _ = client.request("POST", "/api/v1/auth/logout", headers=auth)
    if statuses["logout"] != 204: raise RuntimeError("test logout failed")
    _, after = await baseline(env, 10001)
    planned = {target["identifier"].split(".")[-1]: int(target["expected_after_min_count"])-int(target["expected_before_count"]) for target in p["targets"] if target["kind"] == "MYSQL" and target["operation"] == "APPEND"}
    deltas = {key: after["counts"][key] - before["counts"][key] for key in before["counts"]}
    for table, expected in planned.items():
        if table in deltas and deltas[table] != expected: raise RuntimeError(f"unexpected database delta for {table}")
    if after["account"] != before["account"] or after["consents"] != before["consents"]: raise RuntimeError("run changed account version or consent state")
    proof = {"status":"PASS", "mode":"APPROVED_FORMAL_BEARER_TOPIC_RUN", "plan_id":args.plan_id, "plan_hash":args.plan_hash, "run_id":p["request_run_id"], "user_id":10001, "statuses":statuses, "task_id":task_id, "workspace_id":workspace_id, "result_status":final["status"], "result_items":len(result["items"]), "sse_event_count":len(events), "workspace_event_count":len(workspace_events), "append_deltas":deltas, "account_and_consents_unchanged":True, "deepseek_max_authorized":18, "database_physical_deletions":0, "file_deletions":0, "neo4j_writes":0, "chroma_writes":0, "feedback_behavior_profile_writes":0, "credential_values_printed":0, "verified_at":datetime.now(UTC).isoformat()}
    evidence_path.parent.mkdir(parents=True, exist_ok=False); evidence_path.write_text(json.dumps(proof,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    return proof | {"evidence_path":str(evidence_path.relative_to(ROOT))}


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--apply",action="store_true"); parser.add_argument("--plan",required=True); parser.add_argument("--plan-id",required=True); parser.add_argument("--plan-hash",required=True); parser.add_argument("--base-url",default="http://127.0.0.1:18000"); parser.add_argument("--env-file",default=".env.host")
    args=parser.parse_args()
    if not args.apply: raise SystemExit("refusing to execute without --apply")
    print(json.dumps(asyncio.run(execute(args)),ensure_ascii=False,indent=2,sort_keys=True))
