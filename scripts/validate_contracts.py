#!/usr/bin/env python3
"""Validate G0 JSON Schema, OpenAPI, enum, and configuration contracts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError

from backend.app.shared_kernel.config_bundle import (
    load_strict_json,
    validate_config_bundle_semantics,
)
from backend.app.shared_kernel.contracts.enums import (
    AdaptationState,
    AgentMessageStatus,
    AgentResultStatus,
    AvailabilityStatus,
    BehaviorEventType,
    ChannelRunStatus,
    ConfigStatus,
    DeliveryStrategy,
    EvidenceValidatorStatus,
    ExplanationLevel,
    ExplanationProvider,
    FeedbackType,
    IndexBuildStatus,
    IndexOperation,
    IndexStatus,
    IndexTarget,
    IntentType,
    MessageType,
    NegativeReasonCode,
    OutboxStatus,
    OutputType,
    ReadingStage,
    RecallChannel,
    RecallPhase,
    ResourceType,
    ResourceStateType,
    SnapshotMode,
    SnapshotStage,
    TagSource,
    TaskStatus,
    TriggerScene,
)
from backend.app.shared_kernel.contracts.errors import ErrorCode, WarningCode
from backend.app.llm.prompts import PromptBundle, PromptBundleError


REQUIRED_DOCUMENTS = {
    "contracts/agent/agent-message.schema.json",
    "contracts/agent/agent-result.schema.json",
    "contracts/agent/policy-result.schema.json",
    "contracts/config/rec-config.schema.json",
    "contracts/config/examples/rec-1.0.0.json",
    "contracts/prompts/prompt-bundle.schema.json",
    "contracts/prompts/rec-prompts-v1.0.0.json",
    "contracts/prompts/rec-prompts-v1.0.1.json",
    "contracts/openapi/openapi-v1.json",
    "contracts/verification/g8-readonly-fault-matrix.schema.json",
    "contracts/verification/g8-boundary-change-plan.schema.json",
    "contracts/verification/g8-boundary-apply-evidence.schema.json",
    "contracts/verification/g8-approved-write-reconciliation.schema.json",
    "contracts/verification/g8-final-revalidation-audit.schema.json",
    "contracts/verification/g8-final-runtime-evidence.schema.json",
    "contracts/verification/g8-final-revalidation-plan.schema.json",
    "contracts/safety/examples/change-plan-dry-run.json",
    "contracts/safety/change-plan.schema.json",
}

CHANGE_PLAN_SCHEMA_PATH = "contracts/safety/change-plan.schema.json"
CHANGE_PLAN_EXAMPLE_PATH = "contracts/safety/examples/change-plan-dry-run.json"
CHANGE_PLAN_POLICY_PATH = "docs/SAFETY_POLICY.md"
CHANGE_PLAN_POLICY_HEADING = "### 3.1 最小 ChangePlan 契约"

DATA_DICTIONARY_ENUMS: dict[str, type[Any]] = {
    enum_type.__name__: enum_type
    for enum_type in (
        ResourceType,
        OutputType,
        DeliveryStrategy,
        ExplanationLevel,
        AdaptationState,
        TriggerScene,
        TaskStatus,
        IntentType,
        ReadingStage,
        SnapshotMode,
        SnapshotStage,
        AvailabilityStatus,
        IndexTarget,
        IndexStatus,
        IndexBuildStatus,
        IndexOperation,
        TagSource,
        RecallChannel,
        RecallPhase,
        ChannelRunStatus,
        BehaviorEventType,
        FeedbackType,
        NegativeReasonCode,
        ResourceStateType,
        AgentResultStatus,
        AgentMessageStatus,
        OutboxStatus,
        ExplanationProvider,
        EvidenceValidatorStatus,
        ConfigStatus,
    )
}


@dataclass(frozen=True, slots=True)
class ContractIssue:
    code: str
    path: str
    detail: str


def _issue(code: str, path: str, detail: str) -> ContractIssue:
    return ContractIssue(code=code, path=path, detail=detail)


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def load_json_documents(
    root: Path,
) -> tuple[dict[str, Any], list[ContractIssue]]:
    documents: dict[str, Any] = {}
    issues: list[ContractIssue] = []
    contract_root = root / "contracts"
    if not contract_root.is_dir():
        return {}, [_issue("CONTRACT_DIRECTORY_MISSING", "contracts", "directory not found")]

    for path in sorted(contract_root.rglob("*.json")):
        relative = _relative(path, root)
        try:
            documents[relative] = load_strict_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            issues.append(_issue("INVALID_JSON", relative, str(exc)))

    missing = sorted(REQUIRED_DOCUMENTS - documents.keys())
    issues.extend(
        _issue("REQUIRED_CONTRACT_MISSING", path, "required G0 contract is absent")
        for path in missing
    )
    return documents, issues


def validate_json_schemas(documents: Mapping[str, Any]) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    for path, document in documents.items():
        if not path.endswith(".schema.json"):
            continue
        if not isinstance(document, Mapping):
            issues.append(_issue("SCHEMA_NOT_OBJECT", path, "schema root must be an object"))
            continue
        try:
            Draft202012Validator.check_schema(document)
        except SchemaError as exc:
            issues.append(_issue("INVALID_JSON_SCHEMA", path, exc.message))
    return issues


def _iter_local_refs(node: Any) -> Iterable[str]:
    if isinstance(node, Mapping):
        reference = node.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/"):
            yield reference
        for value in node.values():
            yield from _iter_local_refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_local_refs(value)


def _resolve_local_ref(document: Any, reference: str) -> Any:
    node = document
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, Mapping):
            node = node[part]
        elif isinstance(node, list):
            node = node[int(part)]
        else:
            raise KeyError(part)
    return node


def validate_local_references(documents: Mapping[str, Any]) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    for path, document in documents.items():
        for reference in _iter_local_refs(document):
            try:
                _resolve_local_ref(document, reference)
            except (KeyError, IndexError, TypeError, ValueError):
                issues.append(_issue("LOCAL_REFERENCE_UNRESOLVED", path, reference))
    return issues


def extract_change_plan_policy_example(
    root: Path,
) -> tuple[Any | None, list[ContractIssue]]:
    """Extract the first JSON block from the policy's canonical ChangePlan section."""

    path = root / CHANGE_PLAN_POLICY_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, [
            _issue("CHANGE_PLAN_POLICY_UNREADABLE", CHANGE_PLAN_POLICY_PATH, str(exc))
        ]

    heading_start = text.find(CHANGE_PLAN_POLICY_HEADING)
    if heading_start < 0:
        return None, [
            _issue(
                "CHANGE_PLAN_POLICY_SECTION_MISSING",
                CHANGE_PLAN_POLICY_PATH,
                CHANGE_PLAN_POLICY_HEADING,
            )
        ]

    section_start = heading_start + len(CHANGE_PLAN_POLICY_HEADING)
    next_heading = re.search(r"^###\s+", text[section_start:], flags=re.MULTILINE)
    section_end = (
        section_start + next_heading.start()
        if next_heading is not None
        else len(text)
    )
    section = text[section_start:section_end]
    block = re.search(r"```json\s*\n(?P<body>.*?)\n```", section, flags=re.DOTALL)
    if block is None:
        return None, [
            _issue(
                "CHANGE_PLAN_POLICY_EXAMPLE_MISSING",
                CHANGE_PLAN_POLICY_PATH,
                "section 3.1 must contain a fenced JSON example",
            )
        ]

    try:
        return load_strict_json(block.group("body")), []
    except ValueError as exc:
        return None, [
            _issue(
                "CHANGE_PLAN_POLICY_EXAMPLE_INVALID_JSON",
                CHANGE_PLAN_POLICY_PATH,
                str(exc),
            )
        ]


def _validate_change_plan_instance(
    instance: Any,
    schema: Any,
    path: str,
) -> list[ContractIssue]:
    if not isinstance(schema, Mapping):
        return [
            _issue(
                "CHANGE_PLAN_SCHEMA_INVALID",
                CHANGE_PLAN_SCHEMA_PATH,
                "schema must be an object",
            )
        ]

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    issues: list[ContractIssue] = []
    errors = sorted(
        validator.iter_errors(instance),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    for error in errors:
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        issues.append(
            _issue(
                "CHANGE_PLAN_SCHEMA_VIOLATION",
                path,
                f"{location}: {error.message}",
            )
        )
    return issues


def validate_change_plan_semantics(
    instance: Any,
    path: str = CHANGE_PLAN_EXAMPLE_PATH,
) -> list[ContractIssue]:
    """Enforce safety relationships that JSON Schema cannot compare directly."""

    if not isinstance(instance, Mapping):
        return [_issue("CHANGE_PLAN_SEMANTICS_INVALID", path, "plan must be an object")]

    classification = instance.get("classification")
    allowed_operations = {
        "S0_READ_ONLY": {"READ"},
        "S1_APPEND": {"READ", "CREATE", "APPEND", "START", "COMMIT"},
        "S2_CONTROLLED_UPDATE": {
            "READ",
            "CREATE",
            "APPEND",
            "UPDATE_STATUS",
            "START",
            "STOP",
            "COMMIT",
        },
    }
    issues: list[ContractIssue] = []
    expected_changes = 0
    targets = instance.get("targets")
    if not isinstance(targets, list):
        return [_issue("CHANGE_PLAN_SEMANTICS_INVALID", path, "targets must be an array")]

    for index, target in enumerate(targets):
        if not isinstance(target, Mapping):
            continue
        operation = target.get("operation")
        allowed = allowed_operations.get(classification)
        if allowed is not None and operation not in allowed:
            issues.append(
                _issue(
                    "CHANGE_PLAN_CLASSIFICATION_OPERATION_MISMATCH",
                    path,
                    f"targets.{index}.operation={operation!r} is not allowed for {classification}",
                )
            )

        before = target.get("expected_before_count")
        after = target.get("expected_after_min_count")
        valid_before = isinstance(before, int) and not isinstance(before, bool)
        valid_after = isinstance(after, int) and not isinstance(after, bool)
        if not (valid_before and valid_after):
            continue
        if after < before:
            issues.append(
                _issue(
                    "CHANGE_PLAN_COUNT_DECREASE_FORBIDDEN",
                    path,
                    f"targets.{index}: expected_after_min_count {after} is below expected_before_count {before}",
                )
            )
        else:
            expected_changes += after - before

    max_changes = instance.get("max_changes")
    if isinstance(max_changes, int) and not isinstance(max_changes, bool):
        if expected_changes > max_changes:
            issues.append(
                _issue(
                    "CHANGE_PLAN_MAX_CHANGES_EXCEEDED",
                    path,
                    f"minimum expected increase {expected_changes} exceeds max_changes {max_changes}",
                )
            )
        if classification == "S0_READ_ONLY" and max_changes != 0:
            issues.append(
                _issue(
                    "CHANGE_PLAN_READ_ONLY_CHANGES_FORBIDDEN",
                    path,
                    "S0_READ_ONLY requires max_changes=0",
                )
            )
    return issues


def validate_change_plan_contract(
    root: Path,
    documents: Mapping[str, Any],
) -> list[ContractIssue]:
    """Validate both persisted and policy-embedded examples and prevent drift."""

    schema = documents.get(CHANGE_PLAN_SCHEMA_PATH)
    file_example = documents.get(CHANGE_PLAN_EXAMPLE_PATH)
    if schema is None or file_example is None:
        return []

    issues = _validate_change_plan_instance(file_example, schema, CHANGE_PLAN_EXAMPLE_PATH)
    issues.extend(validate_change_plan_semantics(file_example, CHANGE_PLAN_EXAMPLE_PATH))
    policy_example, extraction_issues = extract_change_plan_policy_example(root)
    issues.extend(extraction_issues)
    if policy_example is None:
        return issues

    issues.extend(
        _validate_change_plan_instance(
            policy_example,
            schema,
            f"{CHANGE_PLAN_POLICY_PATH}#3.1",
        )
    )
    issues.extend(
        validate_change_plan_semantics(
            policy_example,
            f"{CHANGE_PLAN_POLICY_PATH}#3.1",
        )
    )
    if policy_example != file_example:
        issues.append(
            _issue(
                "CHANGE_PLAN_EXAMPLE_DRIFT",
                CHANGE_PLAN_POLICY_PATH,
                f"section 3.1 must equal {CHANGE_PLAN_EXAMPLE_PATH}",
            )
        )
    return issues


def _schema_enum(
    documents: Mapping[str, Any], path: str, *property_path: str
) -> set[str]:
    node: Any = documents[path]
    for part in property_path:
        node = node[int(part)] if isinstance(node, list) else node[part]
    return set(node["enum"])


def _enum_values(enum_type: type[Any]) -> set[str]:
    return {member.value for member in enum_type}


def validate_enum_parity(documents: Mapping[str, Any]) -> list[ContractIssue]:
    required = {
        "contracts/agent/agent-message.schema.json",
        "contracts/agent/agent-result.schema.json",
        "contracts/agent/policy-result.schema.json",
    }
    if not required.issubset(documents):
        return []

    comparisons = (
        (
            "contracts/agent/agent-message.schema.json",
            ("properties", "message_type"),
            MessageType,
        ),
        (
            "contracts/agent/agent-result.schema.json",
            ("properties", "status"),
            AgentResultStatus,
        ),
        (
            "contracts/agent/policy-result.schema.json",
            ("properties", "decision", "properties", "output_type"),
            OutputType,
        ),
        (
            "contracts/agent/policy-result.schema.json",
            ("properties", "decision", "properties", "delivery_strategy"),
            DeliveryStrategy,
        ),
        (
            "contracts/agent/policy-result.schema.json",
            ("properties", "decision", "properties", "explanation_level"),
            ExplanationLevel,
        ),
        (
            "contracts/agent/policy-result.schema.json",
            ("properties", "decision", "properties", "adaptation_state"),
            AdaptationState,
        ),
        (
            "contracts/agent/policy-result.schema.json",
            (
                "properties",
                "retrieval_plan",
                "oneOf",
                "1",
                "properties",
                "channels",
                "items",
                "properties",
                "name",
            ),
            RecallChannel,
        ),
        (
            "contracts/openapi/openapi-v1.json",
            ("components", "schemas", "ResourceType"),
            ResourceType,
        ),
        (
            "contracts/openapi/openapi-v1.json",
            ("components", "schemas", "TriggerScene"),
            TriggerScene,
        ),
        (
            "contracts/openapi/openapi-v1.json",
            ("components", "schemas", "OutputType"),
            OutputType,
        ),
        (
            "contracts/openapi/openapi-v1.json",
            ("components", "schemas", "TaskStatus"),
            TaskStatus,
        ),
        (
            "contracts/openapi/openapi-v1.json",
            ("components", "schemas", "NegativeReasonCode"),
            NegativeReasonCode,
        ),
        (
            "contracts/openapi/openapi-v1.json",
            ("components", "schemas", "FeedbackRequest", "properties", "feedback_type"),
            FeedbackType,
        ),
        (
            "contracts/openapi/openapi-v1.json",
            (
                "components",
                "schemas",
                "InteractionDecision",
                "properties",
                "delivery_strategy",
            ),
            DeliveryStrategy,
        ),
        (
            "contracts/openapi/openapi-v1.json",
            (
                "components",
                "schemas",
                "InteractionDecision",
                "properties",
                "explanation_level",
            ),
            ExplanationLevel,
        ),
        (
            "contracts/openapi/openapi-v1.json",
            (
                "components",
                "schemas",
                "InteractionDecision",
                "properties",
                "adaptation_state",
            ),
            AdaptationState,
        ),
        (
            "contracts/openapi/openapi-v1.json",
            ("components", "schemas", "ErrorCode"),
            ErrorCode,
        ),
        (
            "contracts/openapi/openapi-v1.json",
            ("components", "schemas", "WarningCode"),
            WarningCode,
        ),
    )

    issues: list[ContractIssue] = []
    for path, property_path, enum_type in comparisons:
        try:
            schema_values = _schema_enum(documents, path, *property_path)
        except (KeyError, TypeError):
            issues.append(
                _issue(
                    "SCHEMA_ENUM_MISSING",
                    path,
                    ".".join(property_path) + " must declare enum",
                )
            )
            continue
        python_values = _enum_values(enum_type)
        if schema_values != python_values:
            issues.append(
                _issue(
                    "ENUM_PARITY_MISMATCH",
                    path,
                    f"{enum_type.__name__}: schema={sorted(schema_values)}, "
                    f"python={sorted(python_values)}",
                )
            )
    return issues


def validate_data_dictionary_enum_parity(root: Path) -> list[ContractIssue]:
    relative = "docs/data_dictionary.md"
    path = root / relative
    if not path.is_file():
        return [_issue("DATA_DICTIONARY_MISSING", relative, "canonical enum table is absent")]

    row_pattern = re.compile(r"^\|\s*`(?P<name>[A-Za-z0-9_]+)`\s*\|(?P<values>.+)\|\s*$")
    observed: dict[str, set[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = row_pattern.match(line)
        if not match or match.group("name") not in DATA_DICTIONARY_ENUMS:
            continue
        observed[match.group("name")] = set(re.findall(r"`([^`]+)`", match.group("values")))

    issues: list[ContractIssue] = []
    for name, enum_type in DATA_DICTIONARY_ENUMS.items():
        if name not in observed:
            issues.append(_issue("DATA_DICTIONARY_ENUM_MISSING", relative, name))
            continue
        expected = _enum_values(enum_type)
        if observed[name] != expected:
            issues.append(
                _issue(
                    "DATA_DICTIONARY_ENUM_MISMATCH",
                    relative,
                    f"{name}: docs={sorted(observed[name])}, python={sorted(expected)}",
                )
            )
    return issues


def validate_api_error_code_parity(root: Path) -> list[ContractIssue]:
    relative = "docs/api.md"
    path = root / relative
    if not path.is_file():
        return [_issue("API_DOCUMENT_MISSING", relative, "canonical API contract is absent")]
    pattern = re.compile(r"^\|\s*`(?P<code>[A-Z][A-Z0-9_]+)`\s*\|\s*\d{3}\s*\|")
    documented = {
        match.group("code")
        for line in path.read_text(encoding="utf-8").splitlines()
        if (match := pattern.match(line))
    }
    expected = _enum_values(ErrorCode)
    if documented == expected:
        return []
    return [
        _issue(
            "API_ERROR_CODE_MISMATCH",
            relative,
            f"docs={sorted(documented)}, python={sorted(expected)}",
        )
    ]


def validate_config_bundle(
    config: Any,
    schema: Any,
    path: str = "contracts/config/examples/rec-1.0.0.json",
) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    if not isinstance(config, Mapping) or not isinstance(schema, Mapping):
        return [_issue("CONFIG_CONTRACT_INVALID", path, "config and schema must be objects")]

    try:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(config)
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "<root>"
        issues.append(_issue("CONFIG_SCHEMA_VIOLATION", path, f"{location}: {exc.message}"))

    issues.extend(
        _issue(issue.code, path, issue.detail)
        for issue in validate_config_bundle_semantics(config)
    )
    return issues


def validate_prompt_bundle_contract(
    documents: Mapping[str, Any],
) -> list[ContractIssue]:
    """Validate the committed prompt instance beyond JSON Schema syntax."""

    path = "contracts/prompts/rec-prompts-v1.0.1.json"
    document = documents.get(path)
    if document is None:
        return []
    try:
        PromptBundle.from_document(document, source_path=path)
    except PromptBundleError as exc:
        return [_issue("PROMPT_BUNDLE_CONTRACT_INVALID", path, str(exc))]
    return []


def validate_openapi(document: Any, path: str) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    if not isinstance(document, Mapping):
        return [_issue("OPENAPI_NOT_OBJECT", path, "OpenAPI root must be an object")]
    if not str(document.get("openapi", "")).startswith("3.1."):
        issues.append(_issue("OPENAPI_VERSION_INVALID", path, "openapi must use 3.1.x"))
    info = document.get("info")
    if not isinstance(info, Mapping) or not info.get("title") or not info.get("version"):
        issues.append(_issue("OPENAPI_INFO_INVALID", path, "info.title and info.version are required"))
    paths = document.get("paths")
    if not isinstance(paths, Mapping) or not paths:
        return issues + [_issue("OPENAPI_PATHS_EMPTY", path, "paths must not be empty")]

    schemas = document.get("components", {}).get("schemas", {})
    if not isinstance(schemas, Mapping):
        issues.append(_issue("OPENAPI_SCHEMAS_INVALID", path, "components.schemas must be an object"))
    else:
        for schema_name, schema in schemas.items():
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as exc:
                issues.append(
                    _issue(
                        "OPENAPI_COMPONENT_SCHEMA_INVALID",
                        path,
                        f"{schema_name}: {exc.message}",
                    )
                )

    expected_paths = {
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/recommendation-tasks",
        "/api/v1/recommendation-tasks/{task_id}/clarifications",
        "/api/v1/recommendation-tasks/{task_id}",
        "/api/v1/recommendation-records/{record_id}",
        "/api/v1/recommendation-items/{item_id}/explanation",
        "/api/v1/recommendation-impressions/batch",
        "/api/v1/recommendation-items/{item_id}/feedback",
        "/api/v1/behavior-events",
        "/api/v1/profiles/{user_id}",
        "/api/v1/profiles/{user_id}/refresh",
        "/api/v1/debug/tasks/{task_id}/context",
        "/api/v1/debug/tasks/{task_id}/trace",
        "/api/v1/debug/tasks/{task_id}/policy-decision",
    }
    for missing in sorted(expected_paths - set(paths)):
        issues.append(_issue("OPENAPI_ENDPOINT_MISSING", path, missing))

    operation_ids: set[str] = set()
    destructive_action_tokens = {
        "delete",
        "drop",
        "trun" + "cate",
        "purge",
        "destroy",
        "erase",
        "remove",
        "reset",
        "clear",
    }
    for route, path_item in paths.items():
        if not isinstance(path_item, Mapping):
            continue
        if "delete" in {str(method).lower() for method in path_item}:
            issues.append(
                _issue(
                    "OPENAPI_DESTRUCTIVE_METHOD_FORBIDDEN",
                    path,
                    f"DELETE {route}",
                )
            )
        for method, operation in path_item.items():
            if method.lower() not in {"get", "post", "put", "patch", "head", "options"}:
                continue
            if not isinstance(operation, Mapping):
                issues.append(_issue("OPENAPI_OPERATION_INVALID", path, f"{method.upper()} {route}"))
                continue
            operation_id = operation.get("operationId")
            if not isinstance(operation_id, str) or not operation_id:
                issues.append(_issue("OPENAPI_OPERATION_ID_MISSING", path, f"{method.upper()} {route}"))
            elif not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+_v1", operation_id):
                issues.append(_issue("OPENAPI_OPERATION_ID_FORMAT", path, operation_id))
            elif operation_id in operation_ids:
                issues.append(_issue("OPENAPI_OPERATION_ID_DUPLICATE", path, operation_id))
            else:
                operation_ids.add(operation_id)
            action_tokens = {
                token.lower()
                for token in re.findall(
                    r"[A-Za-z]+",
                    f"{route} {operation_id if isinstance(operation_id, str) else ''}",
                )
            }
            forbidden_actions = sorted(
                action
                for action in destructive_action_tokens
                if any(action in token for token in action_tokens)
            )
            if forbidden_actions:
                issues.append(
                    _issue(
                        "OPENAPI_DESTRUCTIVE_ACTION_FORBIDDEN",
                        path,
                        f"{method.upper()} {route}: {', '.join(forbidden_actions)}",
                    )
                )
            responses = operation.get("responses")
            if not isinstance(responses, Mapping) or not responses:
                issues.append(_issue("OPENAPI_RESPONSES_MISSING", path, f"{method.upper()} {route}"))
            parameters = operation.get("parameters", [])
            has_client_request_id = any(
                isinstance(parameter, Mapping)
                and (
                    parameter.get("$ref")
                    == "#/components/parameters/ClientRequestId"
                    or (
                        parameter.get("in") == "header"
                        and str(parameter.get("name", "")).lower()
                        == "x-request-id"
                    )
                )
                for parameter in parameters
            )
            if not has_client_request_id:
                issues.append(
                    _issue(
                        "OPENAPI_CLIENT_REQUEST_ID_HEADER_MISSING",
                        path,
                        f"{method.upper()} {route}",
                    )
                )
            if method.lower() in {"post", "put", "patch"}:
                if isinstance(responses, Mapping) and "409" not in responses:
                    issues.append(
                        _issue(
                            "OPENAPI_WRITE_CONFLICT_RESPONSE_MISSING",
                            path,
                            f"{method.upper()} {route}",
                        )
                    )
                has_idempotency = any(
                    isinstance(parameter, Mapping)
                    and (
                        parameter.get("$ref")
                        == "#/components/parameters/IdempotencyKey"
                        or (
                            parameter.get("in") == "header"
                            and str(parameter.get("name", "")).lower()
                            == "idempotency-key"
                        )
                    )
                    for parameter in parameters
                )
                if not has_idempotency:
                    issues.append(
                        _issue(
                            "OPENAPI_IDEMPOTENCY_HEADER_MISSING",
                            path,
                            f"{method.upper()} {route}",
                        )
                    )
    return issues


def validate_repository(root: Path) -> tuple[list[ContractIssue], int]:
    documents, issues = load_json_documents(root)
    issues.extend(validate_json_schemas(documents))
    issues.extend(validate_local_references(documents))
    issues.extend(validate_change_plan_contract(root, documents))
    issues.extend(validate_enum_parity(documents))
    issues.extend(validate_data_dictionary_enum_parity(root))
    issues.extend(validate_api_error_code_parity(root))
    issues.extend(validate_prompt_bundle_contract(documents))

    config_path = "contracts/config/examples/rec-1.0.0.json"
    schema_path = "contracts/config/rec-config.schema.json"
    if config_path in documents and schema_path in documents:
        issues.extend(validate_config_bundle(documents[config_path], documents[schema_path]))

    openapi_path = "contracts/openapi/openapi-v1.json"
    if openapi_path in documents:
        issues.extend(validate_openapi(documents[openapi_path], openapi_path))
    return issues, len(documents)


def render_report(issues: Sequence[ContractIssue], parsed_documents: int) -> str:
    return json.dumps(
        {
            "status": "PASS" if not issues else "FAIL",
            "parsed_documents": parsed_documents,
            "issue_count": len(issues),
            "issues": [asdict(issue) for issue in issues],
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    issues, parsed_documents = validate_repository(args.root.resolve())
    print(render_report(issues, parsed_documents))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
