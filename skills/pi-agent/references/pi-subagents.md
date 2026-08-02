# pi-subagents Package

Source: https://pi.dev/packages/pi-subagents

Delegate tasks to focused child agents with sequential chains, parallel groups, dynamic fanout, worktree isolation, acceptance gates, and background runs.

```bash
pi install npm:pi-subagents
```

## Built-in Agents

| Agent | Purpose |
|---|---|
| `scout` | Fast local codebase recon: relevant files, entry points, data flow, risks, where to start |
| `researcher` | Web/docs research with sources; needs `pi-web-access` for `web_search`/`fetch_content`/`get_search_content` |
| `planner` | Concrete implementation plan from existing context; reads and plans, does not edit |
| `worker` | Implementation, including approved oracle handoffs; escalates unapproved decisions |
| `reviewer` | Code review and small fixes against task/plan, tests, edge cases, simplicity |
| `context-builder` | Stronger setup pass: gathers code context and writes handoff material (`context.md`, `meta-prompt.md`) |
| `oracle` (alias `advisor`) | Second opinion before acting; challenges assumptions, no edits |
| `delegate` | Lightweight general delegate close to parent behavior (uses append prompt mode) |

Builtins inherit the current Pi default model unless `subagents.defaultModel` or an override says otherwise. Packaged `planner`, `worker`, `oracle`, and `advisor` default to `context: "fork"`; others default to `fresh`. Builtins opt into project-instruction inheritance so they follow repo rules.

## Commands

```bash
/run <agent> [task]                   # single agent; --bg detached, --fork branched child session
/chain scout "scan" -> planner "plan" # sequential
/chain scout "scan" -> (reviewer "A" | reviewer "B")[concurrency=2,failFast,worktree] -> writer "fix"
/parallel scanner "security" -> reviewer "style"
/run-chain <chainName> -- <task>      # saved .chain.md / .chain.json
/subagent-cost                        # parent + child token usage and cost
/subagents [agent] [model|thinking|prompt|details]
/subagents-doctor                     # read-only setup diagnostics
/subagents-models [agent]             # runtime-loaded model mapping
/subagents-watchdog [status|on|off|recommend-model|model ...|session model ...|check]
/subagents-fleet                      # live fleet inspector (inspection only)
/subagents-stop [run-id]
/subagents-profiles | /subagents-load-profile <name> | /subagents-check-profile <name>
/subagents-refresh-provider-models <provider> [--force] | /subagents-generate-profiles <provider>
```

Steps use `->`; a shared task uses one `--` before the task (`/chain scout planner -- analyze auth`). Inline parallel groups wrap two or more agents in `( ... )` separated by ` | `, only as a complete step, and only when the step opens with `(`. Dynamic fanout is not available inline — use the tool API or a `.chain.json`.

Per-step config appends `[key=value,...]` to the agent name: `output`, `outputMode` (`inline`/`file-only`), `reads` (`a.md+b.md`), `model`, `skills` (`a+b`), `progress`, plus chain-only `as`, `label`, `phase`, `cwd`, `count`, `outputSchema`, `acceptance`. Values must not contain spaces or commas. `output=false`, `reads=false`, `skills=false` disable explicitly. `/run` and `/parallel` ignore chain-only keys.

Add `--bg` for background and `--fork` to branch each child from the parent's current leaf (combinable in either order).

Packaged prompt shortcuts: `/parallel-review`, `/review-loop`, `/parallel-research`, `/parallel-context-build`, `/parallel-handoff-plan`, `/gather-context-and-clarify`, `/parallel-cleanup` (add `autofix` to `/parallel-review` or `/parallel-cleanup` to apply the synthesized fixes).

## Programmatic API (`subagent` tool)

```javascript
{ agent: "worker", task: "refactor auth" }
{ tasks: [{ agent: "scout", task: "audit frontend" }, { agent: "reviewer", task: "audit backend" }], count: 3 }
{ chain: [{ agent: "scout", task: "Gather context" }, { agent: "planner" }, { agent: "worker" }] }
{ chain: [...], async: true, clarify: true }
{ action: "list" | "get" | "create" | "update" | "delete" | "enable" | "disable" | "status" | "interrupt" | "resume" | "stop" | "doctor" }
{ action: "status", id: "<run-id>", view: "fleet" | "transcript", index: 0 }
{ action: "resume", id: "<run-id>", message: "follow-up" }
{ action: "watchdog.recommend-model" }
{ action: "watchdog.configure", model: "recommended", scope: "session" | "user" | "project" }
```

Key parameters: `output` (file or `false`), `outputMode`, `skill` (string/array/`false`), `model`, `concurrency`, `worktree`, `context` (`fresh`/`fork`), `chainDir`, `clarify` (tool calls launch directly unless set), `async`, `cwd`, `timeoutMs`/`maxRuntimeMs`, `turnBudget`, `maxOutput`, `acceptance`.

`subagent_wait` blocks on background work: `{ all: true }`, `{ id }`, `{ timeoutMs }`. Background runs are detached — prefer returning control and letting Pi deliver the completion notification, and use `subagent_wait` only when the current turn must have results before it ends. Headless sessions auto-drain current-session work at `agent_end` as a safeguard.

Dynamic fanout (`.chain.json` or tool API only): a step with `expand: { from: { output: "name", path: "/items" }, item: "target", key: "/path", maxItems: N }` plus `parallel: { agent, label, task: "Review {target.path}", outputSchema }` and `collect: { as: "reviews" }`. The source must be structured output (`as` + `outputSchema`); prose is never parsed, `maxItems` is required, and nested fanout is unsupported.

## Agent Definition Files

Markdown with YAML frontmatter. Precedence low → high: builtin (`~/.pi/agent/extensions/subagent/agents/`), installed package (`pi-subagents.agents` or `pi.subagents.agents` in `package.json`), user (`~/.pi/agent/agents/**/*.md`), project (`.pi/agents/**/*.md`; legacy `.agents/**/*.md` is also read, project config wins collisions). `agentScope: "user" | "project" | "both"` controls discovery.

```yaml
---
name: scout
package: code-analysis        # registers as code-analysis.scout
description: Fast codebase recon
tools: read, grep, find, ls, bash, mcp:chrome-devtools
extensions:                   # omitted = all; empty = none; list = allowlist
subagentOnlyExtensions: ./tools/child-only-search.ts
model: claude-haiku-4-5
fallbackModels: openai/gpt-5-mini, anthropic/claude-sonnet-4
thinking: high
systemPromptMode: replace     # or append (keeps Pi's base prompt)
inheritProjectContext: false
inheritSkills: false
skills: safe-bash, review-checklist
skillPath: ./skills, ../shared-skills
defaultContext: fork
output: context.md
defaultReads: context.md
defaultProgress: true
async: true
timeoutMs: 900000
turnBudget: {"maxTurns":20,"graceTurns":2}
acceptance: {"level":"none","reason":"lightweight lookup"}
acceptanceRole: read-only     # or writer
completionGuard: false        # false for non-implementation validators
interactive: true             # parsed, not enforced in v1
maxSubagentDepth: 1
memory: { scope: project, path: security-reviewer }
---
Your system prompt goes here.
```

Scalar list fields (`tools`, `defaultReads`, `skills`, `skillPath`, `fallbackModels`, `extensions`, `subagentOnlyExtensions`) accept comma-separated or YAML block-list form. Model ids match fuzzily (provider separator, id separator, case, trailing date stamps); a qualified provider query never switches providers.

Custom agents start with a clean prompt: they do not inherit Pi's base prompt, project instruction files, or the skills catalog unless `systemPromptMode: append`, `inheritProjectContext: true`, or `inheritSkills: true`.

Tool selection: omitting `tools` gives Pi's normal builtins; an explicit list is a strict allowlist; an empty field emits `--no-tools`. Allowlisting a name does not load the extension that registers it — load it through normal discovery, `extensions`, `subagentOnlyExtensions`, or a path-like `tools` entry. `mcp:` entries select direct MCP tools (requires `pi-mcp-adapter`; a global `directTools: true` is not sufficient). Children never get the `subagent` tool unless their resolved builtin `tools` explicitly includes it. Missing providers now fail the run before the first model turn instead of continuing silently.

Per-agent memory (`memory: { scope: "project" | "user", path }`) injects the first 200 lines of `MEMORY.md` from `<project>/.pi/agent-memory/<path>` or `~/.pi/agent/agent-memory/<path>` into the child prompt. Agents with write tools are told they may append dated entries; read-only agents get a read-only block. Paths are validated against traversal and symlink escape, and the directory is created lazily by the agent's own `write`.

## Chain Files

`.chain.md` for sequential chains, `.chain.json` when dynamic fanout is needed. Scopes: installed package (`pi-subagents.chains` / `pi.subagents.chains`), user `~/.pi/agent/chains/**`, project `.pi/chains/**`. Project beats user; `.chain.json` beats `.chain.md` within a scope.

```md
---
name: scout-planner
description: Gather context then plan implementation
---

## scout
phase: Context
label: Map auth flow
as: context
output: context.md

Analyze the codebase for {task}

## planner
reads: context.md
model: anthropic/claude-sonnet-4-5:high

Create an implementation plan based on {outputs.context}
```

Config lines (`phase`, `label`, `as`, `outputSchema`, `output`, `outputMode`, `reads`, `model`, `skills`, `progress`) go immediately after the `## agent` header, then a blank line, then the task text. For `output`/`reads`/`skills`/`progress`, behavior is three-state: omitted inherits from the agent, a value overrides, `false` disables. Template variables: `{task}`, `{previous}`, `{chain_dir}`, `{outputs.name}`. Duplicate `as` names, invalid identifiers, and unknown output references fail before child execution.

## Configuration

`~/.pi/agent/settings.json` or `.pi/settings.json` (project wins):

```json
{
  "subagents": {
    "defaultModel": "deepseek-v4-flash",
    "defaultThinking": "medium",
    "defaultExtensions": [],
    "disableThinking": false,
    "disableBuiltins": false,
    "agentOverrides": {
      "reviewer": { "model": "anthropic/claude-sonnet-4", "thinking": "high", "fallbackModels": ["openai/gpt-5-mini"] }
    },
    "watchdog": { "enabled": true, "main": { "model": "anthropic/claude-opus-4-8", "thinking": "high" } },
    "modelScope": { "enforce": true, "allow": ["anthropic/*", "openai/gpt-5-*"] }
  }
}
```

Override fields: `model`, `fallbackModels`, `thinking`, `systemPromptMode`, `inheritProjectContext`, `inheritSkills`, `defaultContext`, `acceptanceRole`, `disabled`, `skills`, `tools`, `systemPrompt`, `extensions`. Use `false` to clear an inherited `defaultContext`/`acceptanceRole`. `defaultModel`/`defaultThinking`/`defaultExtensions` apply to builtin, package, user, and project agents that omit the field; explicit frontmatter and per-run overrides still win. `disableThinking: true` clears bundled builtin thinking defaults for providers that reject `:level` suffixes.

`modelScope.allow` is glob-matched (only `*` is special, case-insensitive) against the resolved `provider/id`. Explicitly passed models that match nothing error and abort; models from frontmatter, `defaultModel`, or the inherited session model only warn. `enforce: true` requires a non-empty `allow`.

Extension config at `~/.pi/agent/extensions/subagent/config.json`: `asyncByDefault`, `forceTopLevelAsync`, `parallel: { maxTasks, concurrency }`, `defaultSessionDir`, `singleRunOutputBaseDir`, `maxSubagentDepth`, `turnBudget`, `intercomBridge: { mode: "always" | "fork-only" | "off", instructionFile }`, `worktreeSetupHook` (+ `worktreeSetupHookTimeoutMs`; receives repo/worktree paths on stdin and must print `{ "syntheticPaths": [...] }`). Nesting depth defaults to 2; tighten or relax with `PI_SUBAGENT_MAX_DEPTH`, config `maxSubagentDepth`, or per-agent frontmatter (per-agent can only tighten).

Profiles live in `~/.pi/agent/profiles/pi-subagents/` and cached provider catalogs in `.../providers/`. Workflow: `/subagents-refresh-provider-models <provider>` → `/subagents-generate-profiles <provider>` → `/subagents-load-profile <provider>.quota`.

## Watchdog

Opt-in adversarial change reviewer — **not** the `reviewer` agent, and not configured by `defaultModel`/`agentOverrides.reviewer`. It runs at the `agent_end` boundary only when the repo's final state changed during the turn; multiple edits coalesce into one review, unchanged/reverted diffs are skipped, and `.pi-subagents/`/`tmp/` artifacts do not trigger it. When enabled it also checks changed TypeScript/JavaScript files for fresh language-server diagnostics (auto-detected `typescript-language-server` from `node_modules/.bin` or PATH; errors become blockers, warnings concerns) bounded by `watchdog.lsp.enabled`, `timeoutMs`, `maxFiles`, `maxDiagnostics`.

Use a strong complementary model: `/subagents-watchdog recommend-model` (current policy is Opus 4.8 high or GPT 5.5 high — use whichever your main session is not). `session model recommended` changes only this session; `model recommended` saves to settings without enabling. Settings keys: `watchdog.main.model`/`.thinking` (omitting `main.model` uses the session model; setting it without a thinking suffix runs with thinking off), `watchdog.children.model`, `watchdog.children.overrides.<agent>.model`.

## Worktrees and Acceptance Gates

`worktree: true` on parallel tasks, chain steps, or group options runs each agent in an isolated git worktree. Requires a git repo with a clean tree; `node_modules/` is symlinked in; task-level `cwd` overrides must match the shared cwd.

```javascript
{ agent: "worker", task: "Implement the fix", acceptance: {
  criteria: ["Patch the bug without widening scope"],
  evidence: ["changed-files", "tests-added", "commands-run", "residual-risks", "no-staged-files"],
  verify: [{ id: "focused", command: "npm test", timeoutMs: 120000 }],
  maxFinalizationTurns: 3
} }
```

Provenance levels reported: `attested`, `checked`, `verified`, `reviewed`, `rejected`. Inline `acceptance=` accepts scalar levels `auto`, `attested`, `checked`; object contracts need the tool API or `.chain.json`.

## Supervisor Coordination

Native, no `pi-intercom` required: children call `contact_supervisor({ reason, message })` with `reason` ∈ `need_decision`, `interview_request`, `progress_update`; the parent replies with `subagent_supervisor({ action: "reply", replyTo, message })` or checks `{ action: "pending" }`. Requests are scoped to the exact Pi session id that spawned the child. If no external `pi-intercom` owns the name, the native channel also exposes `intercom` as a compatibility fallback. `pi install npm:pi-intercom` remains available as a companion.

A foreground child may detach while awaiting a reply: reply first, then `subagent_wait({ id: runId })`.

## Observability

FleetView below the editor shows `main` plus active children with task, elapsed time, and token totals (↑/↓ or j/k to select, Enter to inspect, only when the editor is empty). `/subagents-fleet` opens the inspection-only fleet inspector (Shift+K/J scroll a line, PgUp/PgDn a page, `x`/Ctrl+O toggle tool details, `r` refresh, Esc close; Ctrl+Alt+F opens it mid-turn). Mutations stay explicit via `/subagents-stop`.

Async runs write lifecycle artifacts: `details.asyncDir` holds `status.json`, `events.jsonl`, `output-<index>.log`, `subagent-log-<runId>.md`, with the final summary as `<runId>.json` in Pi's results directory. Stable v1 status fields include `lifecycleArtifactVersion`, `runId`/`id`, `sessionId`, `mode`, `state`, timestamps, `cwd`, `asyncDir`, `sessionFile`, `outputFile`, `workflowGraph`, `steps`, `results`, `totalTokens`, `totalCost`, `model`/`attemptedModels`/`modelAttempts`, `toolCount`, `turnCount`, and nested `children`. Read these files rather than scraping terminal output, and ignore unknown fields for forward compatibility. Lifecycle artifact v3 adds `process-terminal-candidate.json` and `process-terminal.json`; a proof is `observed` only when the live parent saw the runner's `close` event, otherwise `unknown` — never infer exit from `endedAt`, result-file existence, PID disappearance, or lease absence.

## Extension Integration

Versioned in-process event-bus RPC: listen for `subagents:rpc:v1:ready`, emit on `subagents:rpc:v1:request` (`{ version: 1, requestId, method, params }`), read `subagents:rpc:v1:reply:<requestId>`. Methods: `ping`, `status`, `spawn` (async-only), `steer`, `interrupt`, `stop`. `ping.capabilities` advertises `processTerminalProof`, `nonRecoveringSteer`, and `events.asyncComplete`. `pi.events` is in-process only — use file artifacts or `pi-intercom` across processes.

Also exported: `pi-subagents/preflight` (`resolveSubagentLaunchContract`), `pi-subagents/delegation` (`SUBAGENT_DELEGATION_REQUEST_EVENT`, `SUBAGENT_DELEGATION_RESPONSE_EVENT`), and `pi-subagents/background-work` (`registerBackgroundWorkProvider`). Events on the bus: `subagent:async-started`, `subagent:async-complete`, `subagent:control-intercom`, `subagent:result-intercom`, `subagent:process-terminal`.

Optional `@gotgenes/pi-permission-system` adds a runtime `allow`/`ask`/`deny` policy layer via a `permission:` frontmatter block, composing independently with the visibility-based `tools:` allowlist. pi-subagents passes `PI_SUBAGENT_PARENT_SESSION` so headless children can forward `ask` prompts to the parent UI — place `ask` policies on direct children of the interactive session.

## Skills and Bundled Skill

Skills are `SKILL.md` files selected per agent; discovery is project-first (project config `skills/`, project/task packages, project settings, `~/.pi/agent/skills/`, user packages, user settings). Set them via agent defaults, per-run `skill: "tmux, safe-bash"`, or `skill: false`. For chains, top-level `skill` is additive and a step-level value overrides. Missing skills warn instead of failing. When an agent has an explicit `tools` allowlist plus resolved skills, `read` is added so skill files can be loaded.

The package bundles a `pi-subagents` skill for the **orchestrating parent only** — children never receive it, and forked child context is filtered to strip parent-only orchestration instructions, slash/status/control messages, and prior parent `subagent` tool history.

Recommended implementation pattern: clarify → planner → worker → fresh reviewers → worker.
