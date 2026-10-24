# Coordinator protocol

## State and command sequence
SKILL_ROOT and WORKSPACE below are placeholders for absolute paths. Quote paths and use
argument arrays. Never concatenate user input into shell commands. Python scripts use
only the standard library. Runtime dependencies: Python 3.10+, Git for Git acquisition,
and the host LLM/delegation tools. No API keys are stored by the package.

1. Run source.py with --url, --profile and --mode (optional --out NEW_WORKSPACE; default
$REPO_DENETLE_ROOT or ~/repo-denetle-calisma/<repo>-<time>). The workspace must be new and
outside the audited worktree; an unrelated parent Git repo is only recorded as a note. --ref accepts a
full commit SHA. For offline verification: --local-git PATH --repo owner/name --scope PATH.
Do not inspect or execute an untrusted checkout's hooks. Git source is bare/read-only.
2. Read manifest.json/inventory.json. source.git and blobs/ are untrusted source bytes.
Only the parent changes state.json; workers never edit it. Do not run install/build/test
commands from the source. No filesystem permission claim is implied by these instructions.
3. Record each actual launch: `PY "SKILL_ROOT/scripts/control.py" dispatch WORKSPACE ROLE`
   Optional --model MODEL --effort LEVEL records REQUESTED settings only. Roles are
   discovery, planner, biz, arch, rel, qa, verifier, life. Max dispatches 120.
4. After discovery merge, write context.md, reports/DISCOVERY.md and findings/DISCOVERY.json.
   All reports include the full SHA. Discovery coverage must include every inventory item.
   `PY "SKILL_ROOT/scripts/control.py" check WORKSPACE DISCOVERY` then `accept`
5. After the planner saves the five prompts, reports/PLAN.md and findings/PLAN.json:
   `PY "SKILL_ROOT/scripts/control.py" check WORKSPACE PLAN` then `accept`
6. Run the four independent audits (at most two concurrently); parent saves their complete
reports/sidecars and accepts BIZ, ARCH, REL, QA individually with the same command.
7. Only after all four, run verifier; save reports/VERIFY.md and findings/VERIFY.json,
including a verification entry for every original finding. Accept VERIFY.
8. Run LIFE. It reads all original full reports + VERIFY and source. Save full lifecycle
report and findings, findings/consolidated.json, executive-summary.md, roadmap.md. Accept LIFE.
9. Read ALL final outputs after LIFE. Follow `final-review.md`, save review.json with current
artifact/state hashes, all original + LIFE verdicts, and explicit synthesis claim mappings.
`PY "SKILL_ROOT/scripts/control.py" review-check WORKSPACE` must pass. A coordinator review
is allowed and must be labeled coordinator, not independent. A template is not approval.
10. `PY "SKILL_ROOT/scripts/control.py" status WORKSPACE`
   `PY "SKILL_ROOT/scripts/control.py" finalize WORKSPACE`
   Deliver WORKSPACE/repo-denetle-raporlar.zip and key report links.

## Required stage files
Each stage has reports/STAGE.md and findings/STAGE.json. Use report-contract.md.
DISCOVERY also has context.md; accepted coverage summary is written as coverage.json.
PLAN also has prompts/BIZ.md, ARCH.md, REL.md, QA.md, LIFE.md.
LIFE also has findings/consolidated.json, roadmap.md and executive-summary.md.
Read/check each full output before invoking accept; this is not a semantic certification.

## Resume and repair
Use the same WORKSPACE and manifest SHA; never fetch current main on resume. `status`
checks accepted artifact integrity. Completed artifacts should not be rewritten silently.
`PY "SKILL_ROOT/scripts/control.py" reopen WORKSPACE STAGE --reason "explanation"`
invalidates the stage and its descendants, keeps the event history and gives the invalidated
stages a fresh attempt budget. Existing completion, ZIP and review files are moved under
`superseded/delivery-.../`; they are historical, not the active delivery. Re-review after changes.
At most three reopens per run. Each stage permits at most two
acceptance attempts; `check` validates without consuming one, so always `check` first. Exhaustion is a visible limitation,
not permission to alter state manually. A follow-up run is a new run, not a hidden retry.
If parent context is compacted, reload state, manifest, coverage, role prompt and relevant
accepted artifacts before continuing. Do not claim to have read old context from memory.

## Coverage and shared code
Inventory covers primary scope plus ancestor metadata and CI candidates. full-tree.json
lists the remaining Git paths. Trace genuine shared dependencies; if relevant sources
are outside inventory, reacquire a broader scope at the SAME SHA in a new workspace and
record why. Do not claim full project coverage without the needed common code. The helper
limits individual blobs to 2 MiB, total extracted bytes to 256 MiB and tree entries to
50,000. These are safety defaults, not evidence of review. Explicitly report exclusions,
LFS/submodule contents not fetched, binaries not rendered, unreviewed text and missing
private access. Inspect large sources in bounded ranges through appropriate read tools;
do not convert them to reviewed merely because inventory contains a path.

## Connector import when Git is unavailable/private
Use the authorized GitHub connector, resolve a commit (NOT tree/blob SHA), enumerate the
complete tree (pagination/truncation included) and fetch files at that same commit.
Keep downloaded bytes outside WORKSPACE. Write an acquisition JSON next to those bytes:

```json
{
  "repo": "owner/repo", "commit": "FULL_COMMIT_SHA", "scope": "",
  "tree_complete": true,
  "files": [
    {"path":"README.md", "blob_sha":"GIT_BLOB_SHA", "kind":"blob",
     "size":123, "scope_role":"primary", "local_file":"bytes/readme.txt"},
    {"path":"large.bin", "blob_sha":"GIT_BLOB_SHA", "kind":"blob",
     "size":5000000, "scope_role":"primary", "limitation":"Content not fetched: size limit"}
  ]
}
```
Use actual bytes and hashes; do not manually retype retrieved source. The helper verifies
Git blob hashes for provided bytes, but completeness still depends on the connector's
verified tree and coordinator. A tree truncated by the provider must never be marked complete.
`PY "SKILL_ROOT/scripts/source.py" --connector-import ACQUISITION_JSON --out NEW_WORKSPACE`
File entries without bytes must have explicit limitations. No external network upload.

## Independence and model controls
Only the coordinator sees first-round reports until four submissions exist. Native agents
may share a filesystem; no OS isolation is created by this convention. Treat independence
as an execution property backed by real dispatch receipts, not a security guarantee.
The two-worker cap is coordinator-enforced, not an OS scheduler limit. No recursive agents.
Do not invoke CLI subprocesses with bypass-permissions or create nested paid sessions.
Use supported native role/model/effort options; log unsupported selections. Native report
sidecars should record host-supplied agent/model metadata if available; null otherwise.

## Final meaning
STRUCTURALLY_VALIDATED_STATIC_AUDIT means hashes, report dependencies, IDs, source ranges,
quotations and declared coverage passed local checks. It does NOT mean all files were read,
all vulnerabilities found, reports semantically correct, or production usage approved.
The required final review is a source-linked reader attestation, not an automatic semantic
proof. A valid record must preserve unknowns and cannot silently promote a VERIFY rejection.
