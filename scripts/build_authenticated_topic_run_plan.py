#!/usr/bin/env python3
"""Create a read-only exact plan for one authenticated topic recommendation run."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import asyncmy
from jsonschema import Draft202012Validator, FormatChecker

from scripts.validate_runtime_env import read_env


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "contracts/safety/change-plan.schema.json"
READER_FILE = ROOT / ".env.stage2-reader-login.local"
INPUTS = (
    "backend/app/api/identity.py", "backend/app/api/recommendation_runs.py",
    "backend/app/api/agent_workspaces.py", "backend/app/recommendation/application/orchestration.py",
    "frontend/src/api/recommendationRunClient.ts", "scripts/build_authenticated_topic_run_plan.py",
    "scripts/execute_authenticated_topic_run.py",
)
REC_DELTAS = {
    "recommendation_task": 1, "recommendation_task_transition": 8,
    "recommendation_record": 1, "recommendation_item": 8,
    "recommendation_item_explanation": 8, "recommendation_policy_decision": 1,
    "recommendation_trace": 1, "recommendation_agent_message": 7,
    "recommendation_agent_result": 7, "recommendation_agent_artifact": 1,
    "recommendation_orchestration_result": 1,
}
COUNT_TABLES = tuple((*REC_DELTAS, "recommendation_candidate", "iam_auth_session", "iam_refresh_token", "iam_security_event"))


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def commit() -> str:
    value = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError("Git commit is invalid")
    return value


def clean() -> None:
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    if status:
        raise ValueError("worktree must be clean before freezing an authenticated run plan")


async def baseline(env: dict[str, str], user_id: int) -> tuple[str, dict[str, Any]]:
    port = env.get("RECPRO_MYSQL_HOST_PORT") or env.get("RECPRO_MYSQL_PORT")
    if not port or not env.get("RECPRO_MYSQL_DATABASE") or not env.get("RECPRO_MYSQL_USER") or not env.get("RECPRO_MYSQL_PASSWORD"):
        raise ValueError("runtime MySQL configuration is incomplete")
    connection = await asyncmy.connect(host="127.0.0.1", port=int(port), user=env["RECPRO_MYSQL_USER"], password=env["RECPRO_MYSQL_PASSWORD"], db=env["RECPRO_MYSQL_DATABASE"], autocommit=True, connect_timeout=3)
    try:
        async with connection.cursor() as cursor:
            counts = {}
            for table in COUNT_TABLES:
                await cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                counts[table] = int((await cursor.fetchone())[0])
            await cursor.execute("SELECT status, auth_version, role_version FROM iam_user_account WHERE user_id=%s", (user_id,))
            row = await cursor.fetchone()
            if row is None:
                raise ValueError("test reader does not exist")
            account = {"status": str(row[0]), "auth_version": int(row[1]), "role_version": int(row[2])}
            await cursor.execute("SELECT scope, action FROM user_effective_personalization_consent_v WHERE user_id=%s ORDER BY scope", (user_id,))
            consents = {str(scope): str(action) == "GRANT" for scope, action in await cursor.fetchall()}
        return f"mysql://127.0.0.1:{port}/{env['RECPRO_MYSQL_DATABASE']}", {"counts": counts, "account": account, "consents": consents}
    finally:
        connection.close()


def read_g4_candidate_baseline(path: Path) -> int:
    data = json.loads((ROOT / path).resolve(strict=True).read_text())
    if data.get("status") != "PASS" or data.get("candidate_count") != 8:
        raise ValueError("G4 read-only baseline must prove eight candidates")
    value = data.get("candidate_persistence_rows")
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 60:
        raise ValueError("G4 candidate persistence count is invalid")
    channels = data.get("channels")
    if not isinstance(channels, list) or not channels or any(item not in {"MYSQL", "GRAPH", "VECTOR"} for item in channels):
        raise ValueError("G4 baseline returned an invalid recall channel set")
    return value


def plan(run_id: str, database_identity: str, state: dict[str, Any], candidate_rows: int, *, input_text: str, output_type: str) -> dict[str, Any]:
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", run_id) is None:
        raise ValueError("run id is invalid")
    clean(); head = commit(); user_id = 10001
    if not input_text.strip() or len(input_text) > 2000 or output_type not in {"TOPIC_RESOURCES", "READING_PATH"}:
        raise ValueError("recommendation request is outside the public bounds")
    counts = state["counts"]
    deltas = dict(REC_DELTAS); deltas["recommendation_candidate"] = candidate_rows
    deltas.update({"iam_auth_session": 1, "iam_refresh_token": 1, "iam_security_event": 2})
    targets = [{"kind": "MYSQL", "identifier": f"recpro.{table}", "operation": "APPEND", "expected_before_count": counts[table], "expected_after_min_count": counts[table] + delta} for table, delta in deltas.items()]
    targets.extend([
        {"kind": "MYSQL", "identifier": "recpro.iam_user_account:user_id=10001:last-login", "operation": "UPDATE_STATUS", "expected_before_count": 1, "expected_after_min_count": 1},
        {"kind": "MYSQL", "identifier": "recpro.iam_auth_session:planned-session:revoke", "operation": "UPDATE_STATUS", "expected_before_count": 1, "expected_after_min_count": 1},
        {"kind": "MYSQL", "identifier": "recpro.iam_refresh_token:planned-token:revoke", "operation": "UPDATE_STATUS", "expected_before_count": 1, "expected_after_min_count": 1},
        {"kind": "FILE", "identifier": f"artifacts/verification/authenticated-topic-run/{run_id}/acceptance.json", "operation": "CREATE", "expected_before_count": 0, "expected_after_min_count": 1},
    ])
    request_id = str(uuid5(NAMESPACE_URL, f"authenticated-topic:{run_id}:request"))
    session_id = str(uuid5(NAMESPACE_URL, f"authenticated-topic:{run_id}:session"))
    payload = {"request_id": request_id, "session_id": session_id, "scene": "SEARCH_AFTER", "input_text": input_text.strip(), "requested_resource_types": ["BOOK"], "requested_output_type": output_type, "limit": 8}
    marker = "AUTH_TOPIC_BASELINE=" + json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    p: dict[str, Any] = {
        "schema_version": "1.0.0", "plan_id": str(uuid5(NAMESPACE_URL, f"authenticated-topic-plan:{head}:{run_id}")),
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"), "git_commit": head,
        "classification": "S2_CONTROLLED_UPDATE", "mode": "APPLY",
        "intent": "Execute one formally authenticated reader topic recommendation through the public async API and Fetch-SSE-compatible event endpoint. The authenticated reader is user 10001; the task is bounded to eight BOOK results and the existing three recall channels. Login and logout are included solely to prove the browser-facing Bearer identity boundary.",
        "environment": {"environment_id": "recpro-local-authenticated-topic", "workspace": str(ROOT), "host_fingerprint": "sha256:" + hashlib.sha256(f"{database_identity}:{head}:{run_id}".encode()).hexdigest(), "database_identity": database_identity, "index_namespace": "library_resources__hash_char_ngram_v1"},
        "targets": targets, "input_hashes": {x: digest(ROOT / x) for x in sorted(INPUTS)} | {"request_payload": hashlib.sha256(canonical(payload)).hexdigest()},
        "idempotency_key": request_id, "request_run_id": run_id, "max_changes": sum(deltas.values()) + 3,
        "preconditions": [
            marker, "AUTH_TOPIC_REQUEST=" + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            "Exact user 10001 credentials remain only in the protected 0600 local file and must not be logged.",
            "The live workbench is ready at 127.0.0.1:18000 with formal local identity and async recommendation APIs enabled.",
            "The executor sends Authorization: Bearer only; it must not use X-Demo-User-Id.",
            "One in-memory authenticated Agent Workspace may be created and one SSE stream may be read; Workspace audit persistence is disabled.",
            "The only business POST is the frozen topic request; its replay uses the same idempotency key and must append zero rows and issue zero extra model calls.",
            "DeepSeek deepseek-v4-flash is capped at Intent <=2 and Explanation <=16 requests; raw prompts/responses are never persisted.",
            "Expected append deltas are recommendation facts " + json.dumps(deltas, sort_keys=True) + "; only three current-state updates are permitted for login, session/token revocation.",
            "No consent, profile, feedback, behavior, outbox, graph, vector, audit, schema, container, volume, delete, or overwrite operation is allowed.",
        ],
        "safety_assertions": {"file_deletions": 0, "database_physical_deletions": 0, "overwrite_existing": False, "destructive_capabilities_required": False, "counts_must_not_decrease": True},
    }
    p["plan_hash"] = hashlib.sha256(canonical(p)).hexdigest()
    Draft202012Validator(json.loads(SCHEMA.read_text()), format_checker=FormatChecker()).validate(p)
    return p


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    credentials = read_env(READER_FILE.resolve(strict=True))
    if READER_FILE.stat().st_mode & 0o077 or credentials.get("RECPRO_STAGE2_READER_USER_ID") != "10001" or not credentials.get("RECPRO_STAGE2_READER_PASSWORD"):
        raise ValueError("protected synthetic reader material is unavailable")
    env = read_env((ROOT / args.env_file).resolve(strict=True))
    identity, state = await baseline(env, 10001)
    candidate_rows = read_g4_candidate_baseline(Path(args.g4_baseline))
    result = plan(args.run_id, identity, state, candidate_rows, input_text=args.input_text, output_type=args.output_type)
    output = (ROOT / args.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True); handle.write("\n")
    return {"status": "PASS", "mode": "READ_ONLY_AUTHENTICATED_TOPIC_PLAN", "plan_id": result["plan_id"], "plan_hash": result["plan_hash"], "path": str(output.relative_to(ROOT)), "database_writes": 0, "deepseek_requests": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--run-id", required=True); parser.add_argument("--g4-baseline", required=True); parser.add_argument("--output", required=True); parser.add_argument("--env-file", default=".env.host"); parser.add_argument("--input-text", default="多智能体、知识图谱与智慧图书馆"); parser.add_argument("--output-type", choices=("TOPIC_RESOURCES", "READING_PATH"), default="TOPIC_RESOURCES")
    print(json.dumps(asyncio.run(main_async(parser.parse_args())), ensure_ascii=False, indent=2, sort_keys=True))
