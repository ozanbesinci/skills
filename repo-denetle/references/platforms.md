# Hosts: Claude Code, Codex, Antigravity

One real skill folder; each host sees it through a link. No per-host agent files are needed:
role contracts travel inside the worker prompt, so the same procedure runs on all three.

## Install (once per machine)
`PY scripts/kur.py --target all` (Windows: `KUR-WINDOWS.cmd`). It creates:

| Host | Skill path (junction/symlink to this folder) |
|---|---|
| Claude Code (desktop Code tab + CLI) | `~/.claude/skills/repo-denetle` |
| Codex (desktop + CLI) | `~/.codex/skills/repo-denetle` |
| Antigravity (app, IDE, `agy` CLI) | entry in `~/.gemini/config/skills.json` -> this package's parent folder, `include_only: ["repo-denetle"]` |

Antigravity does not follow a junction inside `~/.gemini/config/skills/` (measured 2026-10-23:
the junction was not listed, the `skills.json` entry was), hence the declared entry.

Anything already at those paths is moved to `~/.repo-denetle-yedek/<time>/`, never left inside
a skills folder (a leftover copy would load as a duplicate skill). `--dry-run` previews,
`--uninstall` removes only links that point here, `--mode copy` is for another machine.
Open a NEW session after installing. The installer changes no model, permission, credential
or MCP setting and downloads nothing.

## Claude Code
- Invoke: `/repo-denetle URL` (or ask in words; the description triggers it).
- Subagents: Agent tool, `subagent_type: general-purpose` (has Read/Grep/Glob/Bash/Write).
  Pass `model` per `models.md`. Two Agent calls in ONE message run in parallel.
- Shell: Bash tool (Git Bash) or PowerShell; `python` or `py -3` both work outside sandboxes.
- Workers may write only their assigned report/sidecar paths; parent runs `control.py`.

## Codex
- Invoke: `$repo-denetle URL` or the skill picker.
- Subagents: use the native subagent/spawn tool when it is in your tool list; give each spawn
  the role file text and stage prompt; wait for both before continuing. If no such tool is
  listed, run `--mode sequential` (the reports carry the sequential label). Do not start
  `codex exec` subprocesses as substitutes.
- Python: inside the Codex Windows sandbox `py -3` fails ("No installed Python found"); use
  `python` (measured 2026-10-23, Codex CLI 0.163).
- Subagent tool reported by Codex: `collaboration.spawn_agent`.
- Shell: PowerShell. The Windows sandbox may block the network: request approval for the
  `source.py --url` step once, or use `--local-git`. Write files with apply_patch / file
  tools (UTF-8), not `Set-Content` without `-Encoding utf8`.

## Antigravity
- Invoke: type the skill name (`/repo-denetle URL` if the slash menu lists it) or say
  "repo-denetle skill'iyle denetle: URL". Skills load on demand from their description.
- Subagents: `invoke_subagent` (reported by agy 2026-10-23; two calls in one turn run in
  parallel; `define_subagent`, `send_message`, `manage_subagents` also exist). Alternative:
  `run_workflow` with a short Python script, e.g.
  ```python
  phase("Denetim")
  r = await parallel(["BIZ","ARCH"], lambda s: agent(
        open(rf"{WS}\prompts\{s}.md", encoding="utf-8").read() + ROLE[s],
        schema={"type":"object","properties":{"report_md":{"type":"string"},
                "findings_json":{"type":"string"}},"required":["report_md","findings_json"]},
        role=f"repo-denetle {s}", model="pro"))
  ```
  then the parent writes `report_md`/`findings_json` to the stage files and runs `check`.
  Keep `parallel` at 2 items. Headless `agy -p` cannot prompt for command permission; run the
  audit in the app/IDE or interactive CLI.
- Shell: PowerShell, terminal sandbox may be on; approve the network step or use `--local-git`.
- Antigravity has no Stop/SessionEnd persistence: keep `control.py status` as the resume point.

## All hosts
- Python 3.10+ (PY rule in SKILL.md). Git is needed for `--url`/`--local-git`.
- Live acceptance per host is recorded in `TEST-RESULTS.md`; anything not listed there is
  unverified on that host.
