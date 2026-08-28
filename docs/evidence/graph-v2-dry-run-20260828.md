# LibraMAS knowledge graph v2 dry-run evidence

Run date: 2026-08-28 (Asia/Shanghai)

Command:

```text
.venv-g1-final-py311/bin/python -m scripts.build_book_graph_v2 --target-version lib-books-v2-20260828
```

This was the default read-only mode. It read the existing immutable v1 JSONL
artifacts, did not use `--write`, did not open a database connection, and did
not create import artifacts.

## Bound inputs

| Artifact | SHA-256 |
| --- | --- |
| `graph-plan.json` | `e4b1f382c2ec988f3ea94cee0b256515bb7318bb4843a027cfaa87701a6928c3` |
| `nodes.jsonl` | `d9dba3e2d5a863aa4329cb3bac96d9da969c408fce81458afbb85dc6b7c97c43` |
| `triples.jsonl` | `d8dbcf335c972b18111965fe79943ccae1f870d989b88e180bd6e6473f3585f0` |

Source graph version: `lib-books-v1-20260810`

## Deterministic result

| Measure | v1 source | v2 proposed target | Additive delta |
| --- | ---: | ---: | ---: |
| Nodes | 63,388 | 78,129 | 14,741 |
| Relationships | 191,865 | 206,848 | 14,983 |
| Book / Instance nodes | 14,983 | 14,983 | 0 |
| Work nodes | 0 | 14,741 | 14,741 |
| `INSTANCE_OF` relationships | 0 | 14,983 | 14,983 |
| Item nodes | 0 | 0 | 0 |

Work auto-grouping used normalized title equality plus at least one shared
author. Missing authors and detected identity conflicts were not silently
resolved; they generated in-memory review proposals:

| Review reason | Count |
| --- | ---: |
| `MISSING_AUTHOR_FOR_WORK_MERGE` | 50 |
| `WORK_ISBN_CONFLICT` | 143 |
| `WORK_PUBLISHER_CONFLICT` | 69 |
| Total | 262 |

Persisted review proposal rows: **0**.

## Safety counters

- Database connections: 0
- Neo4j reads: 0
- Neo4j writes: 0
- DeepSeek requests: 0
- Source artifact modifications: 0
- File deletions: 0
- Database physical deletions: 0

The proposed v2 import remains blocked until the code and generated v2
artifacts are frozen into a successor Neo4j ChangePlan and the exact
`plan_id + plan_hash` are approved.
