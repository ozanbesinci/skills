# 1.1.3 - 2026-10-24 (stable)
- Full independent package review: preserve installer source paths, write ZIPs atomically
  without following existing hardlinks, retire stale deliveries on reopen, and disable
  implicit promisor fetch during source reads. Prior deliveries are retained as history.
- Require a hash-bound final review after LIFE, including every finding, scope/measurement
  checks, preserved verdicts and synthesis claim mappings. This is not semantic certification.
- Historical/current applicability and measured/estimated/unknown quantities are explicit
  in auditor and final-review contracts. See TEST-RESULTS.md for current validation scope.
- Git replacement refs are disabled for every source-acquisition Git command, so pinned
  commits and blob contents cannot silently resolve to replacement objects.
- The file-count limit applies to the selected audit scope, including shared candidates;
  the full repository tree remains available for discovery.
- Five regression tests cover commit/blob replacements, narrowed tree/blob scopes,
  oversized scopes and shared-candidate limits.

- ZIP/completion publication rolls back both on an ordinary I/O error; post-delivery
  dispatch/telemetry changes require reopening instead of leaving stale success.
- Windows code suite: 102 tests, 101 passed, 1 symlink-privilege skip. Antigravity
  1.1.3 eight-stage delivery passed structural checks. Its example report was repaired
  on Codex, then independently re-read with 64 final claim mappings. The repaired
  report is a separate release asset; it is not a new Antigravity run.

# 1.1.2 - 2026-10-23 (stable)
Kararlı kabul kapsamı: Windows / Claude Code tam akış. Codex keşif ve izinli GitHub kaynak alımı geçti; Codex ve Antigravity tam denetim kabulü açık.
Güncel 81 testlik kayıt ve dosya hash manifesti yenilendi. Çalışma kodu ve rol sözleşmeleri 1.1.1 ile aynıdır.

# 1.1.1 - 2026-10-23
First end-to-end eight-role run (Claude Code, native, local Git): all stages accepted on the
first attempt. SKILL.md now tells workers to self-validate with the read-only `check`, to read
their prompt files instead of receiving pasted copies, and to be resumed (not relaunched) after
a host usage limit. TEST-RESULTS.md records the run.

# 1.1.0 - 2026-10-23
Renamed `repo-denetim` -> `repo-denetle`; one package for Claude Code, Codex and Antigravity.
- Hosts: per-host agent adapter files removed; role contracts go inline in worker prompts.
  Host mapping (Claude Agent tool, Codex native spawn, Antigravity run_workflow/agent) in
  SKILL.md and references/platforms.md. Antigravity global path `~/.gemini/config/skills`.
- Installer `scripts/kur.py` replaces `install.py`: links (junction/symlink) instead of copies,
  moves anything in the way to `~/.repo-denetle-yedek/` (the old backup inside the skills folder
  loaded as a duplicate skill), `--uninstall`, `--mode copy` for distribution.
- Windows: UTF-8 stdout/stderr (Turkish was mojibake and emoji crashed on pipes); reports and
  JSON accepted with BOM, clear error for non-UTF-8; `read --out FILE`; scripts work under
  `python -I`.
- Source: one `git ls-tree -l` + one `cat-file --batch` instead of two processes per file
  (~120 ms/file on Windows); unsafe/non-UTF-8 repo names become a limitation, not an abort;
  `:` allowed in repo paths; `safe.directory`/fsmonitor hardening for `--local-git`.
- Workspace: optional `--out` (default `~/repo-denetle-calisma/<repo>-<time>` or
  `REPO_DENETLE_ROOT`); blocked only inside the audited worktree, an unrelated parent Git repo
  is a note.
- Gates: `check` (dry run, no attempt used), `reopen` restores attempts with max 3 reopens,
  `telemetry` records host-reported model/agent/tokens, `list` prints the inventory,
  whitespace/Unicode-tolerant quote matching.

# 1.0.1-recovery - 2026-10-23
Reconstructed from the conversational requirements after original 1.0.0 backing bytes
could not be recovered. This is NOT a byte-identical restoration. Native adapters,
commit-pinned source acquisition, structural/evidence gates, coverage ledger, dispatch
budget, report invalidation and installer are newly implemented and locally tested.
Live multi-agent/provider/platform acceptance remains unverified. No historical test
counts or claimed runtime compatibility were carried over as current results.
