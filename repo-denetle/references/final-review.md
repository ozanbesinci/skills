# Required final output review (1.1.3+)

The eight stages remain unchanged. LIFE introduces new findings and prose after VERIFY;
before delivery a real reader must review LIFE, all prior full reports, sidecars, consolidated
findings, executive summary and roadmap against the pinned source. The coordinator may do
this; record `kind: coordinator`. An independent review requires a real native agent and
its host-provided ID. Neither kind certifies semantic truth or production readiness.

1. Finish all stages and telemetry first. Run `control.py review-template WORKSPACE`.
   It prints an UNAPPROVED JSON form with current commit, state SHA256 and every accepted
   artifact hash. Save as UTF-8 `WORKSPACE/review.json` using the host's file-write tool.
2. Read the outputs and source; do not approve by bulk replacing pending fields. Fill the
   reviewer name/kind (and agent_id for independent), then justify four checks:
   - `applicability`: expected behavior's authority, component/version/use and counterevidence.
     Historical code, a current installation and an external successor are different scopes.
   - `measurements`: identify measured, explicitly estimated and unknown quantities. Actual
     model/token/loading/performance evidence must support measured claims. Do not convert
     bytes/lines to tokens, disk presence to per-session loading, or unknowns to zero.
   - `verification_preserved`: preserve VERIFY disagreements and original IDs. Confirming a
     previously disputed/unverified/rejected original requires reopening VERIFY first.
     A final reviewer may downgrade a previously confirmed finding with source-backed reasons.
   - `synthesis`: every material summary/roadmap conclusion has source support, retains the
     final verdict and does not invent new unsupported implications. Check the prose, not
     just counts or matching IDs. Unsupported claims require rewriting the responsible stage.
   Each check has `status: passed|needs_revision`, a nonempty `reason`, and optional pinned
   source `evidence` using report-contract.md. A passed checkbox is a reader attestation.
3. `findings` must classify every original AND LIFE ID exactly once with `finding_id`,
   `status: confirmed|disputed|unverified|rejected`, `reason` and `evidence`. Source evidence
   is required except for an explicitly unverified conclusion. LIFE does not inherit VERIFY.
4. In `claims`, map material synthesis claims to original IDs, including rejected claims
   discussed as such. Use exact quotes from final prose (whitespace normalization allowed):
   `{"id":"CLM-001","path":"executive-summary.md","quote":"Exact final sentence",
   "source_ids":["BIZ-001"],"status":"confirmed"}`. Allowed paths are reports/LIFE.md,
   executive-summary.md and roadmap.md. A confirmed claim may reference only finally confirmed
   findings. Record new material concerns as LIFE findings first, not untracked prose.
   Pure scope/limitation statements need not become defect findings. An empty claim list is
   appropriate only when there are no material finding-based synthesis claims.
5. Record remaining limits in `limitations`. Honest unverified scope gaps do not automatically
   block delivery if clearly labeled in the final prose. An unfinished review, unsupported
   confirmed claim, stale hash or unexplained verdict promotion DOES block delivery.
6. Only after reading and resolving the above set top-level `status: approved` and run
   `control.py review-check WORKSPACE`, then `control.py finalize WORKSPACE`. The ZIP includes
   review.json; completion.json binds its hash and the workflow state hash.

`review-check` validates the record's structure/bindings/declared verdict consistency, not
whether its writer told the truth or understood all prose. Claims omitted by a dishonest or
careless reader cannot be discovered by this deterministic gate. The coordinator remains
responsible for complete semantic review. Never advertise this as automatic fact checking.

Changed state or accepted outputs invalidate the review. Use `reopen` before repairing a
stage; the old delivery/review moves to superseded history. Repeat final reading and record
new hashes. After delivery, dispatch/telemetry changes require reopen rather than leaving
an active stale package. ZIP and completion publication rolls back both on an ordinary
I/O error; this is not a crash-safe multi-file filesystem transaction. If rollback itself
fails, the temporary .delivery-* recovery directory is retained and the command fails.
Do not regenerate a manifest/state/review hash merely to conceal an unread edit.
Older 1.1.2 reports remain historical artifacts; to finalize them with 1.1.3, add a real final
review or repair a copied workspace with explicit provenance. This is not a new full host run.
