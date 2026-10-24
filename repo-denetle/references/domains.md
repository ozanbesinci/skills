# Five domains, twenty areas
All outputs: Turkish, repo-specific, evidence-backed. Interpret the domain relative to
actual project purpose; missing web UI/LLM/DB is not automatically a defect.

## BIZ (4)
Conceptual design; functional analysis; workflows; business rules and decision logic.
Map users/consumers, entities, actions, inputs/outputs, state transitions, boundary cases,
authority, expected behavior and source requirements. Link requirements to actual code,
templates or instructions, and then tests. Distinguish designed from implemented behavior.
Deliver capabilities matrix, scenarios, decision tables and acceptance criteria.

## ARCH (5)
Components; files/dependencies; data architecture/flows; input/output contracts;
LLM orchestration/context (N/A when absent).
Trace entrypoints, imports, calls, APIs/CLI/file messages, persistence and migrations,
transactions/idempotency, caching/invalidation, schema evolution, packaging, platform and
host boundaries. For agents, inspect tools, retrieval, context boundaries, schema checks,
model/host responsibilities. Deliver existing and proposed diagrams separately.

## REL (5)
Security/authorization; errors/exceptions; platform compatibility; non-functional
requirements; performance/resource efficiency.
Threat-model actual assets and trust boundaries. Inspect injection, secrets, file/network
side effects, untrusted parsing, supply chain, authorization, timeouts, retry/backoff,
concurrency, recovery, atomicity and user-visible failure. No destructive probing or
execution of target tests/builds. Check current CVE/support claims with primary sources
only, if needed and permitted. No invented benchmark numbers or generic control bloat.

## QA (3)
Test strategy/scenarios; verification/quality assurance; observability/audit trails.
Separate test definitions, code, recorded runs, reruns and live acceptance. Inspect assertion
quality, negative/boundary cases, fixtures, mocks, integration/contract/regression coverage,
CI gating, bypasses, logs/traces/correlation, data lineage and reproducibility. Vendor tests
are not application tests. No coverage percentages without actual measurement.

## LIFE (3)
Token/context optimization; maintenance/version/change management; consolidated gaps and
roadmap. Independently inspect repetition, routing, cache, retries, cost telemetry if LLM
exists. Bytes are not tokens. Also inspect technical debt, releases, compatibility,
and actual deployment/use: disk presence alone proves neither loading frequency nor token
cost. Keep historical components separate from current ones; separately versioned components
need not share a version number. Quantities are measured, explicitly estimated, or unknown.
migrations, locking, SBOM/licensing, CI/CD and docs. Read all four full audits and VERIFY;
retain IDs, resolve contradictions with source, separate defects from planned features.
Deliver original lifecycle findings, CONS mapping, ordered tasks, affected files, acceptance
tests, dependencies, residual risks. Estimates are assumptions, not delivery promises.
