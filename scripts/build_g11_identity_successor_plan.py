#!/usr/bin/env python3
"""Build the exact forward-only successor for the confirmed partial G11 state."""

from __future__ import annotations
import argparse
from datetime import datetime
import hashlib,json,re,subprocess
from uuid import NAMESPACE_URL,uuid5
from jsonschema import Draft202012Validator,FormatChecker
from scripts.execute_g11_identity_migration import IAM_VIEWS,MAXIMUM_ROWS,MIGRATION_ID,PROJECT_ROOT,SCHEMA,canonical,file_sha256
from scripts.execute_g11_identity_successor import REQUIRED_INPUT_PATHS,expected_fingerprint

def git_commit()->str: return subprocess.run(["git","rev-parse","HEAD"],cwd=PROJECT_ROOT,check=True,capture_output=True,text=True).stdout.strip()
def build_plan(*,reviewed_commit:str,created_at:str,database_identity:str="mysql://127.0.0.1:62306/recpro")->dict[str,object]:
    if re.fullmatch(r"[0-9a-f]{40}",reviewed_commit) is None: raise ValueError("invalid commit")
    parsed=datetime.fromisoformat(created_at.replace("Z","+00:00"))
    if parsed.tzinfo is None or not re.fullmatch(r"mysql://127\.0\.0\.1:[0-9]{1,5}/recpro",database_identity): raise ValueError("invalid timestamp or database")
    targets=[{"kind":"MYSQL","identifier":f"recpro.{name}:schema","operation":"CREATE","expected_before_count":0,"expected_after_min_count":1} for name in IAM_VIEWS]
    targets.extend([
      {"kind":"MYSQL","identifier":"recpro.iam_role:fixed-role-seed","operation":"APPEND","expected_before_count":0,"expected_after_min_count":4},
      {"kind":"MYSQL","identifier":"recpro.iam_permission:fixed-permission-seed","operation":"APPEND","expected_before_count":0,"expected_after_min_count":15},
      {"kind":"MYSQL","identifier":"recpro.iam_role_permission_fact:fixed-grant-seed","operation":"APPEND","expected_before_count":0,"expected_after_min_count":17},
      {"kind":"MYSQL","identifier":f"recpro.recpro_schema_migration:migration_id={MIGRATION_ID}","operation":"APPEND","expected_before_count":0,"expected_after_min_count":1},
    ])
    plan:dict[str,object]={"schema_version":"1.0.0","plan_id":str(uuid5(NAMESPACE_URL,f"recpro:g11-identity-successor:{reviewed_commit}")),"created_at":parsed.isoformat().replace("+00:00","Z"),"git_commit":reviewed_commit,"classification":"S1_APPEND","mode":"APPLY","intent":"Forward-complete the confirmed partial G11 state by retaining all 12 existing empty IAM tables, creating only the 3 missing effective-state views, and appending exactly 37 fixed role, permission, grant, and migration facts. No existing object or row is deleted, replaced, renamed, altered, or updated.","environment":{"environment_id":"recpro_local_research_g11_successor","workspace":str(PROJECT_ROOT),"host_fingerprint":expected_fingerprint(database_identity,reviewed_commit),"database_identity":database_identity,"index_namespace":None},"targets":targets,"input_hashes":{p:file_sha256(PROJECT_ROOT/p) for p in sorted(REQUIRED_INPUT_PATHS)},"idempotency_key":f"g11-identity-successor-{reviewed_commit[:12]}","max_changes":MAXIMUM_ROWS,"preconditions":[f"reviewed successor commit is exactly {reviewed_commit} and remains an ancestor of execution","the user separately approves this unchanged successor plan_id and canonical plan_hash before any database connection","all 12 IAM base tables exist and each contains exactly 0 rows; all 3 IAM views and the G11 marker are absent","the original attempt stopped at CREATE VIEW permission denial and appended exactly 0 fixed seed rows","execution uses the protected root credential only because recpro_migrator lacks CREATE VIEW; no root credential is logged or persisted by the executor","only 3 CREATE VIEW and 4 fixed INSERT IGNORE statements are allowed; destructive and mutable operations are rejected","maximum appended rows are exactly 37; accounts, credentials, sessions, consents, recommendations, DeepSeek, Neo4j, and Chroma changes are 0","failure recovery remains forward-only with no compensating delete, drop, revoke, or truncate"],"safety_assertions":{"file_deletions":0,"database_physical_deletions":0,"overwrite_existing":False,"destructive_capabilities_required":False,"counts_must_not_decrease":True}}
    plan["plan_hash"]=hashlib.sha256(canonical(plan)).hexdigest(); Draft202012Validator(json.loads(SCHEMA.read_text()),format_checker=FormatChecker()).validate(plan); return plan
def main()->int:
    p=argparse.ArgumentParser();p.add_argument("--created-at",required=True);p.add_argument("--reviewed-commit",default=None);a=p.parse_args();print(json.dumps(build_plan(reviewed_commit=a.reviewed_commit or git_commit(),created_at=a.created_at),ensure_ascii=False,indent=2));return 0
if __name__=="__main__":raise SystemExit(main())
