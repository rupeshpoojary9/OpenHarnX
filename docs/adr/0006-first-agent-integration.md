# ADR-0006: First agent integration (Claude Code through hooks)

- Date: 2026-09-27
- Owner: Rupesh Poojary
- Status: accepted for M1
- References: vault ADR-06; PRD 06 ADAPT-01 to ADAPT-08; PRD 19 TEAM-13, TEAM-34; COST-01; Architecture §8.3 and §9; task T03 part D

## Context

M1 needs one real agent integration, not a mock. The adapter must declare, per capability, what it can observe, what it can enforce and what it cannot do. Claude Code 2.1.281 was exercised headless (`claude -p`) in a scratch copy of the fixture on 2026-09-27, with owner approval.

**Isolation:**
- `--setting-sources project`, so only the workspace's own settings loaded
- `--strict-mcp-config`, so no MCP servers
- budget and turn caps on every session

A logging hook was registered for 11 events. It also blocked `Write`, `Edit`, `MultiEdit` and `NotebookEdit` on paths under `protected/`.

## Sessions

| Session | Purpose | Result | Cost reported |
|---|---|---|---|
| 1 | Fix the bug, run tests, use one subagent, try to edit the protected file with the edit tool | Success, 8 turns, 27 s. Minimal correct fix (ceiling division). Edit on `protected/` **blocked** by the hook, file unchanged | $0.19 |
| 2 | Append to the protected file with a shell `echo >>` | **Write succeeded.** The hook saw the command but did not block it | $0.07 |
| 3 | `/compact` on the resumed session 1 | `PreCompact` (trigger `manual`) fired before, `PostCompact` fired after with a 3,989-character summary | $0.24 |
| 4 | SIGTERM during a long command | Exit 143; `Stop` and `SessionEnd` (`reason: other`) still fired; no stray processes; **no JSON result, so no cost report** | none (usage recovered from transcript) |

The agent's fix passed all 21 protected acceptance tests (`examples/backend-bugfix/acceptance`).

## Capability matrix

| Capability | Status | Evidence |
|---|---|---|
| Session start and end, prompt, stop | observed | Hook events in every session, each with `session_id` and `transcript_path` |
| Tool calls with inputs | observed | `PreToolUse` and `PostToolUse` carry `tool_name`, `tool_input` and a `tool_use_id` that pairs them |
| Subagent attribution | observed | Subagent tool calls carry `agent_id` and `agent_type` (`Explore`); `SubagentStop` marks the end |
| Block file-tool writes to a path | enforced, **for the file tools only** | Session 1 |
| Block writes through the shell | **unsupported by hooks** | Session 2: shell redirection bypassed the protection. Enforcement needs an OS sandbox (ADR-07) |
| Blocked call visibility | observed indirectly | A blocked call produced `PreToolUse` with no matching `PostToolUse`. The hook itself should record its denials |
| Checkpoint before compaction | observed (manual trigger) | Session 3. The automatic trigger was not exercised |
| Cancellation | observed | Session 4. Stop and end hooks fire on SIGTERM |
| Cost and usage, completed run | observed | JSON result: `total_cost_usd`, token usage, turns, duration |
| Cost and usage, cancelled run | **partial** | No result JSON. Tokens are recoverable from the transcript, so money is `estimated`, never zero |
| Usage deduplication | required | The session 4 transcript had 7 usage lines for 4 distinct message IDs. A naive sum over-counts by about 1.8x. Deduplicate by message ID (COST-01) |

## Decision

- The first integration is **Claude Code through command hooks**, registered for:
  - `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse` and `PostToolUseFailure`
  - `Stop`, `SubagentStop` and `SessionEnd`
  - `PreCompact` and `PostCompact`
- Usage and cost come from the headless JSON result when present, otherwise from the transcript, deduplicated by message ID and marked `estimated`.
- The hook-based path is declared **observation plus partial enforcement**. Claims of enforced protection require the sandbox boundary in ADR-07.
- The adapter records its own denials, because blocked calls leave no `PostToolUse`.

## Limits

- One Claude Code version (2.1.281), macOS only.
- Automatic compaction was not triggered, and interactive (non-headless) sessions were not exercised.
- Total spend for the four sessions: $0.50 reported, plus the cancelled session's estimated usage.
