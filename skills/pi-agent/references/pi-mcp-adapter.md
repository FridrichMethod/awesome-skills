# pi-mcp-adapter Package

Source: https://pi.dev/packages/pi-mcp-adapter

MCP adapter extension for Pi. Instead of loading hundreds of tool definitions upfront, it exposes one `mcp` proxy tool (~200 tokens) that discovers and calls tools on demand. Servers connect lazily and disconnect when idle; tool metadata is cached to disk so search/describe work offline.

```bash
pi install npm:pi-mcp-adapter
```

Restart Pi after installation. On first run the adapter reads standard MCP files automatically. If you only have host-specific configs (Cursor, Claude Code, Codex, …), run `/mcp setup` to adopt them, or `pi-mcp-adapter init` to scan and add compatibility imports to the Pi agent dir config.

## Configuration Files

Precedence, lowest to highest:

1. `~/.config/mcp/mcp.json` — user-global shared
2. `~/.agents/mcp.json` — user-global tool-agnostic
3. `~/.agents/mcp/mcp.json` — user-global tool-agnostic
4. `<Pi agent dir>/mcp.json` — Pi global override (`~/.pi/agent/mcp.json`, or `$PI_CODING_AGENT_DIR/mcp.json`)
5. `.mcp.json` — project-local shared (preferred for projects)
6. `.pi/mcp.json` — Pi project override

```json
{
  "mcpServers": {
    "chrome-devtools": { "command": "npx", "args": ["-y", "chrome-devtools-mcp@latest"] }
  }
}
```

Host-specific configs are detected but **not** loaded automatically. Opt in with `settings.hostConfigDiscovery: "on"` (or `pi-mcp-adapter init --discover-host-configs`); `"off"` is the default and `"prompt"` detects without activating. Host configs sit below every shared and Pi-owned source.

Import specific host formats explicitly with `"imports": ["cursor", "claude-code", "claude-desktop", "opencode", "vscode", "windsurf", "codex"]`.

`/mcp disable <server>` / `/mcp enable <server>` persist only the `disabled` field into `.pi/mcp.json` (never rewriting the source file or copying credentials); run `/reload` to apply. The manual equivalent is `{ "disabled": true }` in any MCP config.

### SDK Configuration

```ts
import { createMcpAdapter } from "pi-mcp-adapter";
const extension = createMcpAdapter({ config: { mcpServers: { docs: { url: "https://mcp.example.com/mcp", lifecycle: "eager" } } } });
```

A supplied `config` is a complete isolated snapshot — never merged with files, imports, or `--mcp-config`, and cloned per adapter/session. Status, reconnect, explicit `/mcp-auth <server>`, proxy calls, and direct tools still work; setup and no-argument auth/status panels report the limitation. With `configPath` and no `config`, normal file merging applies and that path outranks argv and `--mcp-config`. The package ships TypeScript source, so standalone Node processes need a TS-capable loader (e.g. `node --import tsx`).

OAuth credentials are stored in the OS credential store keyed by configured server name, with URL binding so credentials cannot be reused for a different server URL. `settings.oauthDir` / `MCP_OAUTH_DIR` are legacy plaintext `tokens.json` import locations only.

## Server Options

| Field | Description |
|---|---|
| `command`, `args` | stdio transport; mutually exclusive with `url` and `socket` |
| `socket` | `rmcp-mux` Unix socket path; supports `${VAR}`, `$env:VAR`, `~` |
| `env`, `cwd` | Interpolation supported; an `env` value starting with `!` runs a command at connect (`!!` escapes) |
| `url`, `headers` | StreamableHTTP with SSE fallback; interpolation supported, missing URL vars fail before any request |
| `auth` | `"bearer"` or `"oauth"` |
| `oauth.*` | `grantType` (`authorization_code` default, or `client_credentials`), `clientId`, `clientSecret`, `scope`, `redirectUri` (exact localhost callback for pre-registered clients), `clientName`, `clientUri` |
| `bearerToken` / `bearerTokenEnv` | Token or env var name; interpolation and `!command` supported |
| `lifecycle` | `"lazy"` (default), `"eager"`, `"keep-alive"`, `"lazy-keep-alive"` |
| `idleTimeout` | Minutes before idle disconnect (overrides global) |
| `requestTimeoutMs` | Per-server request timeout; omitted or `<= 0` uses the MCP SDK default |
| `exposeResources` | Expose MCP resources as tools (default `true`) |
| `directTools` | `true`, `string[]`, or `false` |
| `includeTools` / `excludeTools` | Names or glob patterns; `excludeTools` applies after `includeTools` |
| `debug` | Show server stderr (default `false`) |
| `trace` | Metadata-only JSONL protocol tracing for this server |
| `disabled` | Keep visible in config/status but block connections, auth, tools, resources (only literal `true`) |

Secret values in `headers`, `bearerToken`, `oauth.clientSecret`, and stdio `env` may use a leading `!command` resolved at connect/auth time: stdin and stderr suppressed, stdout capped at 1 MiB and trimmed, 10-second limit, non-empty output required. Commands never run during discovery, merging, previewing, hashing, or rendering config.

**Lifecycle modes** — `lazy`: connect on first tool call, disconnect after idle, cached metadata keeps search working. `eager`: connect at startup, no auto-reconnect, no idle timeout unless set. `keep-alive`: connect at startup with health checks and auto-reconnect. `lazy-keep-alive`: connect on first use, then stay resident with auto-reconnect. Any enabled `eager`/`keep-alive` server also triggers initialization at extension load, supporting hosts that never emit `session_start`.

**rmcp-mux** — point `socket` at an [`rmcp-mux`](https://github.com/VetCoders/rmcp-mux) service socket to share one stdio server across Pi sessions. The adapter owns only its client socket; the mux owns the upstream process, routing, restart policy, and socket permissions. A socket is an explicit trusted local endpoint.

## Global Settings

```json
{ "settings": { "toolPrefix": "server", "idleTimeout": 10, "requestTimeoutMs": 30000, "trace": { "enabled": true } } }
```

`toolPrefix` (`"server"` default, `"short"` strips a `-mcp` suffix, `"none"`, `"mcp"` prefixes `mcp__`), `idleTimeout` (minutes, default 10, `0` disables), `requestTimeoutMs`, `showStatusIcon` (default `true`), `hostConfigDiscovery`, `oauthDir`, `directTools` (global default, default `false`), `disableProxyTool`, `autoAuth` (default `false`), `sampling` (default `true` when UI approval is available; honors `modelPreferences.hints`), `samplingAutoApprove` (required for sampling in non-UI sessions), `elicitation` (default `true` with UI), `outputGuard`, `trace` (`{ enabled, file, maxBytes: 262144, maxEvents: 10000 }`; the per-session JSONL defaults to `.pi/mcp-traces/` and never records payloads, prompts, arguments/results, auth data, or URLs).

## Output Guard

On by default: inline text is capped at **50 KiB / 2000 lines** (matching Pi's `bash` guard), with the full text spilled to a temp file whose path is included so the agent can `read`/`grep` it. Image blocks pass through unchanged. In proxy mode `details.mcpResult` stays raw when its JSON is ≤ 16 KiB; larger results become a compact summary with the raw JSON spilled to a temp file (direct tools never carry `mcpResult`). Tune with `{ maxBytes, maxLines, detailsMaxBytes }`; disable with `"outputGuard": false` or `MCP_OUTPUT_GUARD=0`. Temp files are mode `0600` under the system temp dir and are not cleaned up automatically.

## Direct Tools

```json
{ "mcpServers": { "github": { "directTools": ["search_repositories", "get_file_contents"] } } }
```

`true` registers all of a server's tools individually, an array registers only those (original MCP names), omitted/`false` is proxy-only. Per-server overrides the global default. `includeTools`/`excludeTools` filter direct tools, proxy search/list/describe, and the `/mcp` panel. Each direct tool costs ~150–300 tokens, so use targeted sets of 5–20; for 75+ tool servers stay on the proxy.

Direct tools register from the metadata cache (`~/.pi/agent/mcp-cache.json`, or `$PI_CODING_AGENT_DIR/mcp-cache.json`), so no startup connections are needed. The first session after adding `directTools` falls back to proxy-only while the cache populates, then hot-loads. Servers advertising list-change notifications refresh the current session. Force a refresh with `/mcp reconnect <server>`.

## Proxy Tool API

```javascript
mcp({ })                                        // status / list servers
mcp({ server: "name" })                         // server details (+ instructions preview)
mcp({ search: "screenshot navigate" })          // search tools (OR'd words)
mcp({ describe: "tool_name" })
mcp({ instructions: "name" })                   // full server instructions
mcp({ tool: "chrome_devtools_take_screenshot", args: { format: "png" } })
mcp({ connect: "server-name" })                 // connect or refresh
mcp({ action: "ui-messages" })
mcp({ action: "auth-start", server: "name" })
mcp({ action: "auth-complete", server: "name", args: { redirectUrl: "http://localhost:19876/callback?code=...&state=..." } })
```

`args` accepts a JSON object or a JSON string. Search covers MCP tools **and** Pi extension tools (prefixed `[pi tool]`, listed first). Names fuzzy-match on hyphens and underscores. Server `instructions` surface at three levels: a truncated head in the proxy tool description, a longer preview in `mcp({ server })`, and the full text via `mcp({ instructions })` — captured at connect time and cached.

Remote/headless OAuth uses `auth-start` then `auth-complete` (pass `redirectUrl`, or just `args: { code }`). Persistent OAuth requires an available OS credential store — on headless Linux, an unlocked Secret Service/libsecret keyring; the adapter fails closed rather than storing plaintext.

## Commands

`/mcp` (interactive panel: status, tools, direct/proxy toggles, reconnect, `ctrl+a` or Enter for OAuth), `/mcp setup`, `/mcp tools`, `/mcp prompts`, `/mcp reconnect [server]`, `/mcp disable <server>`, `/mcp enable <server>`, `/mcp logout <server>`, `/mcp-auth [server]`.

## Prompts, Elicitation, UI

MCP prompt templates register as slash commands `/mcp__<server>__<prompt>`, refreshed on connect. Arguments support positional and `key=value` forms with quoting; required arguments are validated before `prompts/get`. Results flatten into one user message preserving `[user]`/`[assistant]` markers.

Elicitation forms use Pi's `select()`/`input()` dialogs with validation and a review step; explicit refusal maps to MCP `decline`, dismissal to `cancel`. URL mode is TUI-only, always shows requesting server/host/URL, and requires consent; `-32042` URL-required tool errors are handled — retry the original call after completing the browser step.

MCP UI resources open in a native macOS window via Glimpse (`pi install npm:glimpseui`) or fall back to the browser. `MCP_UI_VIEWER=browser|glimpse|none` forces or suppresses the viewer (`none` still runs the tool and returns inline results). UIs talk back — message types `prompt`, `intent`, `notify`, `message`, plus custom types forwarded as intents — retrieved with `mcp({ action: "ui-messages" })` (each with `type`, `sessionId`, `serverName`, `toolName`, `timestamp`). Calling the same tool again pushes a new result into the open window instead of replacing it. Tool consent gates whether UIs may call MCP tools (never / once-per-server / always). Browser controls: Cmd/Ctrl+Enter completes, Escape cancels.

## Status Snapshots

```ts
import { MCP_STATUS_EVENT, type McpStatusSnapshot } from "pi-mcp-adapter";
pi.events.on(MCP_STATUS_EVENT, (snapshot) => { /* read-only */ });
```

Includes `totalTools`, `totalResources`, `connectedCount`, `disabledCount`, and per-server `name`, `status` (connected, cached, failed, needs-auth, not-connected, disabled), `toolCount`, `disabled`, plus `resourceCount` when known and `failedAgoSeconds` on active failure. Reading status never connects a lazy server, starts auth, or exposes clients, transports, credentials, or server definitions. An initial snapshot follows initialization; an empty snapshot is emitted on shutdown.

## Behavior Notes and Limitations

npx-based servers resolve to direct binaries, skipping the ~143 MB npm parent process. Advertised `outputSchema` supports JSON Schema draft-07 and 2020-12 (unstamped schemas use the SDK's 2020-12 default), and returned `structuredContent` is validated for both proxy and direct calls. Results render compactly (first three wrapped lines plus a Ctrl+O expand hint) while the model still receives the full result.

Limitations: no cross-session server sharing (each Pi session runs its own server processes, unless using rmcp-mux); MCP sampling is text-only (context inclusion, tools, stop sequences, audio, and images are rejected); inline images follow Pi's image display settings.

Subagents (`pi-subagents`) receive direct MCP tools only when listed with an `mcp:` prefix in their `tools:` frontmatter — a global `directTools: true` is not enough. See `references/pi-subagents.md`.
