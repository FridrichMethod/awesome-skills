# pi-web-access Package

Source: https://pi.dev/packages/pi-web-access

Web search, content extraction, GitHub repo cloning, PDF extraction, YouTube and local-video understanding for Pi.

```bash
pi install npm:pi-web-access
```

Requires Pi v0.37.3+. Works with no API keys — Exa MCP provides zero-config search, and OpenAI search can reuse Codex auth from `/login`. Optional binaries for frame extraction: `brew install ffmpeg` (frames, thumbnails, local video duration) and `brew install yt-dlp` (YouTube stream URLs). Without them, transcripts and Gemini-based analysis still work.

## Tools

### web_search

Searches via OpenAI, Brave, Parallel, Tavily, SERPdive, AnySearch, self-hosted SearXNG, Exa, Perplexity, or Gemini and returns a synthesized answer with citations.

```javascript
web_search({ query: "TypeScript best practices 2025" })
web_search({ queries: ["query 1", "query 2"], workflow: "auto-summary" })
web_search({ query: "latest news", numResults: 10, recencyFilter: "week" })
web_search({ query: "...", domainFilter: ["github.com", "-old.example.com"], provider: "openai" })
```

Parameters: `query`/`queries`, `numResults` (default 5, max 20), `recencyFilter` (`day`/`week`/`month`/`year`), `domainFilter` (prefix `-` to exclude), `provider` (`auto` or an explicit provider), `includeContent`, `workflow` (`none`, `summary-review` default, `auto-summary`).

In `auto` mode the fallback order is configured SearXNG → OpenAI (when suitable and available) → Exa (direct API if keyed, MCP if not) → Brave → Parallel → Tavily → SERPdive → Perplexity → Gemini API → Gemini Web (only with browser cookies enabled). AnySearch is explicit-only and never auto-selected.

### fetch_content

Extracts readable markdown from URLs or local files, auto-detecting GitHub repos, YouTube videos, PDFs, local video files, and regular pages.

```javascript
fetch_content({ url: "https://example.com/article" })
fetch_content({ urls: ["url1", "url2"] })
fetch_content({ url: "https://github.com/owner/repo" })
fetch_content({ url: "https://youtube.com/watch?v=abc", prompt: "What libraries are shown?" })
fetch_content({ url: "/path/to/recording.mp4", prompt: "What error appears on screen?" })
fetch_content({ url: "...", timestamp: "23:41-25:00", frames: 4 })
```

Parameters: `url`/`urls`, `prompt` (question about a video), `timestamp` (single `"23:41"`, range `"23:41-25:00"`, or bare seconds; accepts `H:MM:SS`, `MM:SS`, seconds), `frames` (max 12), `forceClone` (clone GitHub repos over the 350 MB threshold).

### get_search_content

Retrieves stored content from previous searches or fetches. Content is stored in full but returned in bounded slices by default; page through with `offset`/`limit` (30,000-character bounds).

```javascript
get_search_content({ responseId: "abc123", urlIndex: 0 })
get_search_content({ responseId: "abc123", url: "https://...", offset: 30000 })
```

### source_check

Checks a claim and returns a machine-readable artifact with exact passage citations.

```javascript
source_check({ claim: "The API supports streaming responses",
  queries: ["API streaming documentation"], fetchContent: true, domainFilter: ["docs.example.com"] })
```

Results are deduplicated and capped at 20 sources; `fetchContent` fetches at most 5 pages. The artifact carries claim status (`supported`, `contradicted`, `unclear`, `missing-evidence`), source-quality hints, SHA-256 content hashes, and passage IDs with exact source offsets. Search and fetch errors stay in the artifact instead of being discarded. Artifacts are stored with the session and retrieved through `get_search_content` by `responseId`.

## Capabilities

- **GitHub repos** are cloned locally instead of scraped: root URLs return the tree plus README, `/tree/` paths return directory listings, `/blob/` paths return file contents, and the agent gets a local path to explore with `read`/`bash`. Repos over 350 MB use a lightweight API view (override with `forceClone`). Commit-SHA URLs go through the API. Clones are cached per session and wiped on session change; private repos need the `gh` CLI. Setting `githubClone.enabled: false` only skips the clone/API specialization — `fetch_content` still handles the URL through normal extraction.
- **YouTube** via Gemini: visual descriptions, timestamped transcripts, chapter markers, and the thumbnail. Fallback: Gemini Web (cookies enabled) → Gemini API → Perplexity (text only). Handles `/watch?v=`, `youtu.be/`, `/shorts/`, `/live/`, `/embed/`, `/v/`.
- **Local video** (`/`, `./`, `../`, or `file://`): MP4, MOV, WebM, AVI and other common formats up to 50 MB for Gemini analysis; a thumbnail frame is included when ffmpeg is present. Timestamp/frame extraction uses ffmpeg directly and works on larger files.
- **PDFs** are text-extracted and saved to `~/Downloads/` as markdown so the agent can `read` sections. No OCR.
- **Blocked pages**: Readability → Next.js RSC flight-data parser → configured Firecrawl (cache-only by default) → Jina Reader → Parallel → Gemini URL Context → Gemini Web extraction when cookies are enabled.

## Commands

```text
/websearch [queries]            # open the curator; comma-separated pre-fill
/curator [on|off|summary-review]
/search                         # browse stored session results
/google-account                 # active Google account for Gemini Web
```

`Ctrl+Shift+W` toggles a live activity monitor of request/response data. Results are injected when you approve the curator summary or send selected results without one; on timeout the curator auto-submits with a deterministic fallback summary. If a browser cannot be opened (Docker, WSL, SSH, headless), the curator URL appears in the tool output.

## Configuration

Config defaults to `~/.pi/web-search.json`, or `web-search.json` under `PI_CODING_AGENT_DIR` / `XDG_CONFIG_HOME/pi`. Every field is optional. Config changes require a Pi restart.

```json
{
  "openaiApiKey": "sk-...",
  "braveApiKey": "BSA_...",
  "exaApiKey": "exa-...",
  "parallelApiKey": "...",
  "tavilyApiKey": "tvly-...",
  "serpdiveApiKey": "sd_live_...",
  "serpdiveModel": "krill",
  "perplexityApiKey": "pplx-...",
  "geminiApiKey": "AIza...",
  "geminiBaseUrl": "https://my-gateway.example.com/gemini",
  "cloudflareApiKey": "...",
  "searxngBaseUrl": "https://search.example.com",
  "firecrawlBaseUrl": "https://crawl.example.com",
  "firecrawlApiKey": "fc-...",
  "firecrawlApiVersion": "v2",
  "firecrawlFreshScrape": false,
  "provider": "openai",
  "searchRouting": { "providers": ["openai", "brave", "exa"], "fallbackOn": ["transient", "quota", "network"] },
  "webSearch": { "enabled": true },
  "toolNames": { "webSearch": "web_search", "sourceCheck": "source_check", "fetchContent": "fetch_content", "getSearchContent": "get_search_content" },
  "searchModel": "gemini-2.5-flash",
  "summaryModel": "anthropic/claude-haiku-4-5",
  "workflow": "summary-review",
  "curatorTimeoutSeconds": 20,
  "chromeProfile": "Profile 2",
  "allowBrowserCookies": false,
  "githubClone": { "enabled": true, "maxRepoSizeMB": 350, "cloneTimeoutSeconds": 30, "clonePath": "/tmp/pi-github-repos" },
  "youtube": { "enabled": true, "preferredModel": "gemini-3-flash-preview" },
  "video": { "enabled": true, "preferredModel": "gemini-3-flash-preview", "maxSizeMB": 50 },
  "fetchContent": { "domainPolicy": { "allow": ["example.com"], "deny": ["blocked.example.com"] } },
  "shortcuts": { "curate": "ctrl+shift+s", "activity": "ctrl+shift+w" },
  "ssrf": { "allowRanges": ["198.18.0.0/15"], "trustEnvProxy": false }
}
```

**Credential sources** (provider API-key fields only): `$NAME` / `${NAME}` reads one env var; a leading `!` runs a trusted local command at provider request time; `$$` and `$!` escape literal prefixes. Commands never run at load or tool registration — each selected provider request re-runs them with a 5-second timeout, 16 KiB output limit, minimized environment, and one-line non-empty stdout requirement (`OP_SESSION_*` is forwarded for 1Password). An explicit source overrides legacy env vars and fails that provider locally rather than falling back on a stale credential.

**Legacy env vars** (lower precedence than an explicit source, higher than literal config values): `OPENAI_API_KEY`, `BRAVE_API_KEY`, `PARALLEL_API_KEY`, `TAVILY_API_KEY`, `SERPDIVE_API_KEY`, `ANYSEARCH_API_KEY`, `FIRECRAWL_API_KEY`, `EXA_API_KEY`, `GEMINI_API_KEY`, `PERPLEXITY_API_KEY`, `GOOGLE_GEMINI_BASE_URL`, `CLOUDFLARE_API_KEY`. Also `SEARXNG_BASE_URL`, `FIRECRAWL_BASE_URL`, `FIRECRAWL_API_VERSION`, `FIRECRAWL_FRESH_SCRAPE`, `SERPDIVE_MODEL`, `PI_ALLOW_BROWSER_COOKIES`.

**Routing**: `provider` (or `searchProvider`) sets the default and takes precedence over `searchRouting`. `searchRouting` opts into an ordered `providers` list plus `fallbackOn` (`transient`, `quota`, `network`) — only those typed failures continue to the next candidate. Named providers stay strict and exhausted routes return per-provider diagnostics. `webSearch.enabled: false` unregisters the search and source-check tools while leaving fetch/content tools. `toolNames` renames the public tools for environments where the defaults collide.

**Models**: `searchModel` overrides only the Gemini API model used for search (default `gemini-2.5-flash`). `summaryModel` sets the curator/`auto-summary` draft model; when Pi's `enabledModels` is configured, summaries are limited to that allowlist and fall back to a deterministic summary rather than calling an unrelated model.

**Security**: `fetchContent.domainPolicy` is an optional hostname allow/deny policy checked before HTTP(S) handling and each redirect this extension follows — bare hostnames match subdomains, `deny` wins, and local/non-HTTP sources are exempt. It adds to, not replaces, the SSRF guard. `ssrf.allowRanges` exempts specific CIDRs (for TUN + fake-IP proxies such as Surge/Clash/Mihomo/Stash); it is off by default and all-address CIDRs are rejected. `ssrf.trustEnvProxy` skips local DNS preflight for proxied hostnames only, still blocking localhost, literal private IPs, and `NO_PROXY` matches. Firecrawl requests are cache-only (`lockdown: true`) unless `firecrawlFreshScrape` is set — only enable that for an isolated Firecrawl deployment, since this extension cannot control the Firecrawl server's own egress.

**SERPdive** `serpdiveModel` picks retrieval depth: `krill` (free default, extracted page content, answer assembled from sources), `mako` (1 credit, fact-carrying sentences plus synthesized answer), `moby` (1.5 credits, full readable content plus cited answer). Unrecognized values fall back to `krill` so a typo cannot cost money. SERPdive has no time-range or domain parameter, so `recencyFilter` is a ranking hint appended to the question and `domainFilter` is applied locally; `numResults` maps to `max_results`, a cap between 1 and 10.

**Gemini gateway**: `geminiBaseUrl` / `GOOGLE_GEMINI_BASE_URL` overrides the Gemini API host (bare host, no trailing slash or version segment). When the host contains `gateway.ai.cloudflare.com`, auth uses `cf-aig-authorization: Bearer <token>` from `cloudflareApiKey`/`CLOUDFLARE_API_KEY` and `GEMINI_API_KEY` is not required for generate-content calls — but local video upload still uses Google's Files API directly.

## Limits and Limitations

Perplexity is capped at 10 requests/minute client-side; content fetches run 3 concurrent with a 30s timeout per URL; Gemini handles videos up to ~1 hour; local video upload is 50 MB max. Chromium cookie extraction for Gemini Web is opt-in (`allowBrowserCookies: true` or `PI_ALLOW_BROWSER_COOKIES=1`) and may trigger a macOS Keychain dialog; cookie DBs are copied to a temporary read-only working copy. Private/age-restricted YouTube videos may fail on all paths, PDFs are text-only, GitHub branch names with slashes may misresolve file paths, and non-code GitHub URLs (issues, PRs, wiki) fall through to normal web extraction.
