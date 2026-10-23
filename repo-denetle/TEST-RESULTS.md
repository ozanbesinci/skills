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
- A complete eight-role audit in Codex or Antigravity (only the Claude Code run above).
- Antigravity network acquisition and Codex acquisition without network approval.
- Model/effort selection actually honored by each host; token telemetry.
- Semantic correctness or completeness of audit reports.
- macOS/Linux installation.
