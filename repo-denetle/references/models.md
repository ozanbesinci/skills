# Model policy (runtime capability dependent)
Profiles change model/effort REQUESTS only. Evidence requirements never drop.

| Role | guvence (default) | dengeli | derin |
|---|---|---|---|
| discovery | fast capable model, medium | fast, medium | strong, high |
| planner | strong, high | strong, medium | strong, high |
| biz/arch/rel/qa/verifier/life | strongest code-reasoning, high | strongest, high | strongest, highest supported |

## Per host
- Claude Code: Agent tool `model` - `sonnet` for discovery/planner, `opus` for auditors,
  verifier and life. If a model is refused or unavailable, inherit and record the limitation;
  do not retry the same unavailable model.
- Codex: subagents inherit the session model/effort unless the spawn tool accepts explicit
  settings; then request the strongest listed model for auditors. Never claim a switch the
  tool did not confirm.
- Antigravity: `agent(..., model=...)` tiers - `"flash"` for discovery, `"pro"` for planner,
  auditors, verifier, life. `"inherit"` when tiers are not offered.

A skill cannot change the parent session's model.

## Telemetry
`control.py dispatch` records the REQUESTED model/effort. After the worker returns, record only
what the host actually reported with `control.py telemetry WORKSPACE D-000N --model ...
--agent-id ... --tokens N`; leave unknown values empty (null). Bytes are not tokens. No price
or saving claims without real telemetry and current pricing. Profiles are not spend caps; the
dispatch cap (120) only limits launches.
