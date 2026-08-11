#!/usr/bin/env python3
"""Read-only verification of the reviewed local Prompt Bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import DEFAULT_PROMPT_BUNDLE_SHA256
from backend.app.llm.prompts import (
    DEFAULT_PROMPT_BUNDLE_PATH,
    PromptBundleError,
    load_prompt_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_PROMPT_BUNDLE_PATH)
    parser.add_argument("--expected-sha256", default=DEFAULT_PROMPT_BUNDLE_SHA256)
    parser.add_argument("--expected-version", default="prompt-v1")
    args = parser.parse_args()
    try:
        bundle = load_prompt_bundle(
            args.bundle,
            expected_sha256=args.expected_sha256,
            expected_version=args.expected_version,
        )
    except (PromptBundleError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1

    print(
        json.dumps(
            {
                "status": "PASS",
                "source_path": bundle.source_path,
                "source_sha256": bundle.source_sha256,
                "schema_version": bundle.schema_version,
                "bundle_version": bundle.bundle_version,
                "locale": bundle.locale,
                "task_count": len(bundle.tasks),
                "tasks": [
                    {
                        "prompt_id": task.prompt_id,
                        "agent_name": task.agent_name,
                        "capability": task.capability,
                        "version": task.version,
                        "template_sha256": task.template_sha256,
                        "evidence_only": task.evidence_only,
                        "max_input_chars": task.max_input_chars,
                        "max_output_tokens": task.max_output_tokens,
                        "fallback_strategy": task.fallback_strategy,
                    }
                    for task in bundle.tasks.values()
                ],
                "allowed_tools": [],
                "database_reads": 0,
                "database_writes": 0,
                "external_requests": 0,
                "files_deleted": 0,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
