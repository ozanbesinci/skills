# Validation results - Repo Denetle 1.1.3 (stable)

Date: 2026-10-24. Windows, Python 3.14.8, Git 2.54.0.windows.1.
Current full suite: **102 tests, 101 passed, 1 skipped, 0 failures** (47.741 seconds).
Command: `python -X utf8 -B -m unittest discover -s tests -t tests -v`.
The single skip remains Windows symlink privilege; junction and hardlink tests actually ran.

Independent full-file review covered the original 27-file 1.1.3 candidate and then re-read
the code/instruction fixes. Requested model/effort: gpt-6-astra/high; independently supplied
actual model/effort/token telemetry unavailable. Four original defects were reproduced in
isolated fixtures and fixed: installer self-source relocation, ZIP hardlink overwrite,
stale delivery after reopen, and implicit promisor fetch. Fix review also caught completion
publication rollback and post-finalization execution-record mutations; both were fixed.

16 new regression tests cover these changes and the final review record: missing/unapproved
or stale review, historical applicability/measurement checks, all LIFE IDs, preserving prior
VERIFY verdicts, claim/source verdict consistency, truthful unverified delivery, write failure
rollback and preflight installation overlap. The final manifest includes two new files.
An earlier suite had only a stale-manifest failure after a Windows write-permission error;
the manifest was refreshed and the final complete run above passed.

Review records remain source-linked reader attestations, not automatic semantic certification.
Current tests use isolated local fixtures; no audited target code/tests/builds were executed.
Old eight-role host runs below are historical 1.1.2 evidence. Current 1.1.3 evidence follows.

## Antigravity 1.1.3 and final report review - 2026-10-24

A fresh Antigravity native run completed all eight stages for the pinned historical
updater scope at d60f202e22b2ac03287da4f0225c9ebbd0b24db0 (10 files / 884 lines).
The original 31-file ZIP SHA-256 is
`5daa788e1bf64119b01a61a526aaefd5c74b07cace35c6d9e9f1ca7085792e5c`.
Stage/hash gates passed, but its final prose had five source/authority/measurement
problems. Those gates alone were not treated as semantic acceptance.

A copied workspace was repaired on Codex: VERIFY and LIFE were reopened; a real
independent verifier re-read every source and original full report. The coordinator
rewrote LIFE, summary and roadmap; a different independent reader reviewed all final
outputs and 64 claim mappings. All 20 original IDs and 13 groups remain visible.
Final verdicts: 4 conditional P3 confirmed, 6 disputed, 9 rejected, 1 unverified.
This is an example audit of the historical target, not a count of defects in this skill.
The corrected 31-file ZIP SHA-256 is
`2b9a665cc0d055ba6466090b9e3a21719cb6e128b7735d4e42cf1f5d687f7ea7`.
CRC and 31/31 raw-byte readback passed; original sources/delivery were preserved.
The final review binds 26 accepted artifact hashes; its SHA-256 is
`e3fe4d0cc838c819eed926d7be31ba74dafa1d880767593d6914b65394e7780a`.

Release includes the corrected example report as a separate ZIP and SHA-256 asset.
Report repair/independent review on Codex is not a new eight-role Antigravity run.
Actual model/effort/token telemetry was unavailable; requested settings are not
reported as independently confirmed actual models. macOS/Linux were not tested.
Static evidence and reader approval are not production/security certification.
Earlier records below retain their original version and scope.

## Earlier 1.1.3 source-fix verification

Date: 2026-10-24. PR #1 source repair; no release package published.
Windows, Python 3.12.14, Git for Windows.

Full suite: **86 tests, 85 passed, 1 skipped, 0 failures.**
Command: `python -m unittest discover -s tests -t tests -v`.
Five added regression tests cover real Git commit/blob replacement refs, narrowed
tree/blob scopes, rejection of oversized selected scopes and shared-candidate counts.
The three regression tests run before the repair reproduced both review findings.
Limits are reduced in the scope tests to exercise the same boundary with small fixtures.
This does not establish new full-host audit acceptance. Historical results follow.

# Validation results - Repo Denetle 1.1.2

Date: 2026-10-23
Machine: Windows 11 Enterprise, Python 3.14.8, Git for Windows.

## Unit/integration suite
Command: `py -3 -m unittest discover -s tests -t tests`
Result: **81 tests, 80 passed, 1 skipped, 0 failures.** The skip is `test_symlink_blocked`:
creating a symlink needs a Windows privilege this account does not have (junctions do not).
New in 1.1.0: installer (junction + Antigravity skills.json registry, backup outside skills
folders, uninstall, copy mode), `check` without attempt use, reopen budget, BOM/CRLF and
non-UTF-8 reports, whitespace-tolerant quotes, telemetry, repo paths with `:`, workspace
rules incl. Windows 8.3 short paths, batch Git snapshot (60+ files, duplicates, empty file,
byte budget), UTF-8 `read` on a pipe and with `--out`, `python -I` CLI, manifest integrity.

## Measured on this machine
- Source acquisition, 301-file local repo: 1.0.1 = 36.2 s (120 ms/file), 1.1.0 = 4.9 s (16 ms/file).
- `control.py read` of a Turkish+emoji line through a pipe: 1.0.1 crashed (`charmap` codec),
  1.1.0 prints it correctly.

## Live host checks (2026-10-23, short probes, no audit run)
| Host | Skill discovered | `control.py read` (Turkish + emoji) | Subagent tool reported |
|---|---|---|---|
| Claude Code CLI (`claude -p`, sonnet) | yes, `~/.claude/skills/repo-denetle` | correct | `Agent` |
| Codex CLI 0.163 (`codex exec`, read-only sandbox) | yes, `~/.codex/skills/repo-denetle` | correct with `python`; `py -3` fails in the sandbox | `collaboration.spawn_agent` |
| Antigravity CLI (`agy -p`) | yes, via `~/.gemini/config/skills.json`; a junction in `~/.gemini/config/skills/` was NOT discovered | correct with `python` | `invoke_subagent` (+ `run_workflow`) |

## End-to-end run: Claude Code, native mode (2026-10-23)
- Target: local Git `ozanbesinci/skills`, commit `d60f202e22b2ac03287da4f0225c9ebbd0b24db0`, scope
  `teklif-degerlendirme/skills/teklif-degerlendirme-guncelle` (+ ancestor metadata): 10 files,
  50,314 bytes, acquired with `--local-git` and the default workspace under `~/repo-denetle-calisma`.
- Delegation: Claude Code `Agent` tool, `general-purpose`; 9 dispatches (discovery x2 sonnet,
  planner sonnet, BIZ/ARCH/REL/QA/VERIFY/LIFE opus), never more than two at once.
- Gates: all 8 stages (DISCOVERY..LIFE) accepted on the FIRST attempt. Every worker ran the
  read-only `check` on its own files before returning; `finalize` returned
  `STRUCTURALLY_VALIDATED_STATIC_AUDIT`, coverage 10/10 files fully reviewed (self-reported).
- Output: 45 audit findings (BIZ 12, ARCH 12, REL 10, QA 11) + LIFE 7 = 52 IDs; VERIFY 34
  confirmed / 11 disputed / 0 rejected; 27 CONS entries cover all 52 IDs. Report ZIP has 30
  files and no `blobs/` or `source.git/`.
- Parent spot-check: the top finding (updater accepts manifest schema {1,2} only,
  `guncelle.py` L153; repo manifest is schema 3, L68) was confirmed in source by the parent.
- Telemetry: host-reported `actual_model` claude-opus-5-5 for opus workers; sonnet workers did
  not report a model (null). Subagent tokens reported by the host: 2,265,382 in total.
- Interruption: the account session limit stopped LIFE mid-way (LIFE.json and
  consolidated.json already written). After the reset the SAME agent was resumed with
  SendMessage and finished; no state was lost and no stage was retried.
- Turkish text survived end to end: discovery facts, reports and `read` output are correct UTF-8.

## Codex partial acceptance (2026-10-23)
- Native DISCOVERY accepted: 10/10 files, 884 lines, same pinned commit as Claude.
- GitHub URL acquisition with approved network access passed; all 10 path/hash/size entries match local Git (50,314 bytes).
- PLAN and subsequent stages remain pending; no full Codex acceptance is claimed.
- Runtime scripts and role contracts are unchanged. Current 81-test log replaces the old 64-test log.
- skill-creator quick_validate could not run: optional PyYAML absent. Package frontmatter tests passed.

## Not verified
- A fresh complete eight-role audit for 1.1.3 in each host. Later 1.1.2 Codex/Antigravity
  workflow results are recorded outside this historical subsection; they do not certify semantics.
- Antigravity network acquisition and Codex acquisition without network approval.
- Actual model/effort/token telemetry beyond the specific historical values recorded above.
- Semantic correctness or completeness of audit reports.
- macOS/Linux installation.
