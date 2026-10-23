# Report contract
## Evidence and severity
Use BIZ-001, ARCH-001, REL-001, QA-001, LIFE-001. Preserve source IDs during consolidation.
P0: evidenced critical risk requiring a stop of the affected operation/release.
P1: high impact; P2: moderate; P3: low-impact improvement. Version drift or missing tests
are not automatically P0. Label defect, risk, debt, documentation, missing requirement,
or unverified claim. Explain expected behavior's authority and counterevidence.

Evidence levels: documentation claim, static implementation, test source, historical run,
current isolated run, live acceptance, unverified. This package's normal mode is STATIC:
no target program/test/build execution. Never label a historical PASS as a current run.

## Markdown report
Include full commit, scope, executive summary, applied/N/A checks, actual files/ranges read,
architecture or workflow as applicable, findings with source links, counterevidence,
fixes/acceptance criteria, and limitations. Each finding has impact, root cause or labeled
hypothesis, confidence, exact file/range, and a measurable verification plan. Do not quote
secrets. An absent control needs a bounded search description, not an invented citation.

## JSON sidecar
Save UTF-8 JSON. All stages use this shape; findings may be empty:
```json
{
  "stage": "BIZ",
  "commit": "FULL_COMMIT_SHA",
  "report_path": "reports/BIZ.md",
  "mode": "static",
  "coverage": [
    {"path": "src/example.py", "start": 1, "end": 40, "status": "reviewed", "sha256": "INVENTORY_SHA256"},
    {"path": "image.png", "status": "unreviewed", "reason": "Binary renderer unavailable"}
  ],
  "findings": [
    {"id": "BIZ-001", "title": "Concrete issue", "severity": "P2",
     "kind": "risk", "confidence": "medium", "evidence_level": "static",
     "observed": "Actual behavior", "expected": "Expected behavior and its authority",
     "impact": "User or technical effect", "recommendation": "Specific correction",
     "acceptance": "Observable passing test criterion",
     "evidence": [{"path": "src/example.py", "start": 12, "end": 14,
                    "sha256": "INVENTORY_SHA256", "quote": "Optional exact substring"}]
    }
  ],
  "limitations": [],
  "telemetry": {"requested_model": "profile selection", "actual_model": null,
                "requested_effort": "high", "actual_effort": null}
}
```
`quote` is optional. It must be a substring of the cited lines; matching ignores whitespace
differences and Unicode composition, nothing else. Copy it from `control.py read` output; if
the console showed replacement characters (U+FFFD) or other mojibake, re-read with `--out FILE` or omit the quote.
`sha256` is the inventory `sha256` of that path (see `control.py list`/`inventory.json`).
Save every report/JSON as UTF-8. Run `control.py check` before `accept`.
Use actual paths; the example path is not a project requirement. Discovery sidecar must
mention EVERY inventory item: reviewed ranges, partial ranges, or explicit unreviewed
reason. Other stages list files they actually consulted; do not copy discovery coverage.
For VERIFY add `verification`: one entry per original finding with `finding_id`, `status`
(confirmed/disputed/unverified/rejected), `reason`, and `evidence` array. Include no new
findings there; return new concerns to the relevant auditor or LIFE for substantiation.

For LIFE additionally save findings/consolidated.json as an array of
`{"id":"CONS-001","source_ids":["BIZ-001"],"disposition":"open","reason":"..."}`.
Every original finding ID, including rejected ones, must appear. Do not erase disagreements.
No findings is valid, not proof of safety. Parent validates semantic completeness beyond
script checks; scripts cannot prove an agent read or understood a file.
