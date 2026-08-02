# G1 local orchestration

`compose.yaml` requires a unique `COMPOSE_PROJECT_NAME`. Use the convention
`libramas-g1-<researcher>-<instance>` so networks, images, and named volumes do
not collide with another run.

Copy `.env.compose.example` to the ignored `.env.compose` file, replace the two
identity segments, and supply new local passwords. The checked-in examples keep
all password values empty so they cannot be mistaken for usable credentials.

The MySQL initialization hook runs only for a new named volume. It creates the
runtime identity with schema-level `SELECT` and `INSERT`. G1 has no business
tables yet, so the approved table-specific `UPDATE` grants are intentionally
deferred to the forward-only G2 migration that creates those tables. The backend
readiness evaluator rejects a schema-wide `UPDATE` grant.

The same new-volume hook creates the platform-owned `recpro_runtime_probe` table
and appends one marker keyed by `COMPOSE_PROJECT_NAME`. Readiness verifies that
marker, the selected database identity, UTF-8 configuration, current runtime
identity and minimum grants. The G1 acceptance verifier then reads exact marker
counts before and after a safe restart; those read-only queries never alter data.

Every first-time formal G1 acceptance run must use a project name whose
containers, two networks and all three named volumes do not already exist. The
verifier refuses collisions before it starts anything and requires a clean Git
worktree so the evidence manifest maps to one exact commit. After verification,
the stopped containers and volumes remain retained; routine starts may reuse
that same verified project, but another first-time acceptance run must use a new
identity.

The lifecycle stop operation is owned by the root `Makefile` and uses Compose
stop semantics. The orchestration files define no cleanup or volume-retention
automation; named MySQL and Neo4j volumes remain available for the next start.
The empty G1 Chroma location is also a named `chroma_data` volume shared by the
backend and worker. Its contents are versioned in later gates; G1 reports the
capability as disabled and never fabricates an active index.
