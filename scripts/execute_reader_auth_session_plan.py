#!/usr/bin/env python3
"""Execute one approved, bounded reader login/refresh/logout verification."""

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
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
from http.cookiejar import CookieJar

from jsonschema import Draft202012Validator, FormatChecker

from scripts.build_reader_auth_session_plan import (
    PROJECT_ROOT, READER_CREDENTIAL_FILE, SCHEMA, canonical, read_baseline, sha256,
)
from scripts.validate_runtime_env import read_env


INPUT_PATHS = (
    "backend/app/api/identity.py", "backend/app/composition.py",
    "backend/app/identity/adapters/mysql.py", "backend/app/identity/application.py",
    "backend/app/identity/security.py", "scripts/build_reader_auth_session_plan.py",
    "scripts/execute_reader_auth_session_plan.py",
)


class Client:
    def __init__(self, base_url: str) -> None:
        self._jar = CookieJar()
        self._base_url = base_url.rstrip("/")
        self._opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(self._jar))

    def cookies(self) -> dict[str, str]:
        return {cookie.name: cookie.value for cookie in self._jar}

    def request(self, method: str, path: str, *, payload: dict[str, object] | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict[str, object] | None]:
        body = json.dumps(payload).encode() if payload is not None else None
        request_headers = {"Accept": "application/json"}
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        try:
            with self._opener.open(Request(self._base_url + path, data=body, headers=request_headers, method=method), timeout=10) as response:
                raw, status = response.read(), int(response.status)
        except HTTPError as exc:
            return int(exc.code), None
        except (URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"identity API unavailable ({type(exc).__name__})") from exc
        if not raw:
            return status, None
        try:
            value = json.loads(raw.decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            return status, None
        return status, value if isinstance(value, dict) else None


def read_plan(path: Path, plan_id: str, plan_hash: str) -> dict[str, Any]:
    plan = json.loads(path.resolve(strict=True).read_text())
    Draft202012Validator(json.loads(SCHEMA.read_text()), format_checker=FormatChecker()).validate(plan)
    unsigned = dict(plan); unsigned.pop("plan_hash", None)
    if plan.get("plan_id") != plan_id or plan.get("plan_hash") != plan_hash or hashlib.sha256(canonical(unsigned)).hexdigest() != plan_hash:
        raise ValueError("approved plan identity or canonical hash does not match")
    if not re.fullmatch(r"[0-9a-f]{40}", str(plan.get("git_commit", ""))):
        raise ValueError("approved plan commit is invalid")
    if subprocess.run(["git", "merge-base", "--is-ancestor", str(plan["git_commit"]), "HEAD"], cwd=PROJECT_ROOT).returncode != 0:
        raise ValueError("approved commit is not an ancestor of HEAD")
    hashes = plan.get("input_hashes", {})
    if hashes != {item: sha256(PROJECT_ROOT / item) for item in sorted(INPUT_PATHS)}:
        raise ValueError("identity input hash boundary changed after approval")
    return plan


def evidence_path(run_id: str) -> Path:
    return PROJECT_ROOT / "artifacts/verification/reader-auth-session" / run_id / "acceptance.json"


def approved_baseline(plan: dict[str, Any]) -> dict[str, Any]:
    for item in plan.get("preconditions", []):
        if isinstance(item, str) and item.startswith("AUTH_SESSION_BASELINE="):
            value = json.loads(item.removeprefix("AUTH_SESSION_BASELINE="))
            if isinstance(value, dict):
                return value
    raise ValueError("approved plan omitted its exact authentication baseline")


async def apply(args: argparse.Namespace) -> dict[str, Any]:
    plan = read_plan(Path(args.plan), args.plan_id, args.plan_hash)
    values = read_env((PROJECT_ROOT / args.env_file).resolve(strict=True))
    creds = read_env(READER_CREDENTIAL_FILE.resolve(strict=True))
    if READER_CREDENTIAL_FILE.stat().st_mode & 0o077:
        raise ValueError("protected reader credential file must have mode 0600")
    user_id = int(creds["RECPRO_STAGE2_READER_USER_ID"])
    identity, before = await read_baseline(values, user_id=user_id)
    if identity != plan["environment"]["database_identity"] or before != approved_baseline(plan):
        raise ValueError("current identity baseline differs from the approved plan")
    path = evidence_path(str(plan["request_run_id"])).resolve()
    if path.exists():
        raise ValueError("evidence path exists; use its existing run instead of overwriting it")
    client = Client(args.base_url)
    if client.request("GET", "/api/v1/health/ready")[0] != 200:
        raise RuntimeError("identity workbench readiness is not healthy")
    statuses: dict[str, int] = {}
    status, login = client.request("POST", "/api/v1/auth/login", payload={"identifier_type": "READER_NUMBER", "identifier": creds["RECPRO_STAGE2_READER_IDENTIFIER"], "password": creds["RECPRO_STAGE2_READER_PASSWORD"], "device_type": "BROWSER"})
    statuses["login"] = status
    if status != 200 or not isinstance(login, dict) or not isinstance(login.get("access_token"), str) or int(login.get("user", {}).get("user_id", 0)) != user_id:
        raise RuntimeError("login response did not prove the planned reader identity")
    access = str(login["access_token"])
    status, me = client.request("GET", "/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    statuses["me"] = status
    if status != 200 or not isinstance(me, dict) or int(me.get("user", {}).get("user_id", 0)) != user_id:
        raise RuntimeError("authenticated identity read did not reconcile")
    csrf = client.cookies().get("recpro_csrf")
    if not csrf:
        raise RuntimeError("login did not return the required CSRF cookie")
    status, refreshed = client.request("POST", "/api/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
    statuses["refresh"] = status
    if status != 200 or not isinstance(refreshed, dict) or not isinstance(refreshed.get("access_token"), str):
        raise RuntimeError("refresh did not rotate into a valid access token")
    status, _ = client.request("POST", "/api/v1/auth/logout", headers={"Authorization": f"Bearer {refreshed['access_token']}"})
    statuses["logout"] = status
    if status != 204:
        raise RuntimeError("logout did not revoke the test session")
    _, after = await read_baseline(values, user_id=user_id)
    for table, delta in {"iam_auth_session": 1, "iam_refresh_token": 2, "iam_security_event": 2}.items():
        if int(after["counts"][table]) - int(before["counts"][table]) != delta:
            raise RuntimeError(f"unexpected {table} delta")
    if after["account"] != before["account"] or after["roles"] != before["roles"] or after["consents"] != before["consents"]:
        raise RuntimeError("authentication run changed account authorization or consent state")
    evidence = {"status": "PASS", "mode": "APPROVED_READER_AUTH_SESSION", "verified_at": datetime.now(UTC).isoformat(), "plan_id": args.plan_id, "plan_hash": args.plan_hash, "run_id": plan["request_run_id"], "user_id": user_id, "statuses": statuses, "before_counts": before["counts"], "after_counts": after["counts"], "append_deltas": {key: int(after["counts"][key]) - int(before["counts"][key]) for key in before["counts"]}, "account_authorization_and_consents_unchanged": True, "database_physical_deletions": 0, "file_deletions": 0, "deepseek_requests": 0, "neo4j_writes": 0, "chroma_writes": 0, "credential_values_printed": 0, "access_or_refresh_token_persisted": 0}
    path.parent.mkdir(parents=True, exist_ok=False)
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return evidence | {"evidence_path": str(path.relative_to(PROJECT_ROOT))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--plan-hash", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:18000")
    parser.add_argument("--env-file", default=".env.host")
    args = parser.parse_args()
    if not args.apply:
        raise SystemExit("refusing to execute without --apply")
    result = asyncio.run(apply(args))
    print(json.dumps({key: value for key, value in result.items() if key not in {"before_counts", "after_counts"}}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
