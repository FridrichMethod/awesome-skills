# Themes

Source: https://pi.dev/docs/latest/themes

Themes are JSON files defining TUI colors.

## Locations

- Built-in: `dark`, `light`
- Global: `~/.pi/agent/themes/*.json`
- Project: `.pi/themes/*.json` (only after project trust)
- Packages: `themes/` directories or `pi.themes` entries in `package.json`
- Settings: `themes` array
- CLI: `--theme <path>` (repeatable)

Disable discovery with `--no-themes`. Select via `/settings` or `{"theme": "my-theme"}`. On first run Pi detects the terminal background and defaults to `dark` or `light`. Editing the active custom theme file hot-reloads it for immediate feedback.

## Format

```json
{
  "$schema": "https://raw.githubusercontent.com/earendil-works/pi/main/packages/coding-agent/src/modes/interactive/theme/theme-schema.json",
  "name": "my-theme",
  "vars": { "primary": "#00aaff", "secondary": 242 },
  "colors": { "accent": "primary", "muted": "secondary", "text": "" }
}
```

- `name` is required, must be unique, and must not contain `/`.
- `vars` is optional — reusable colors referenced by name from `colors`.
- `colors` must define all 51 tokens. `thinkingMax` is the only optional one and falls back to `thinkingXhigh`.
- `$schema` enables editor auto-completion and validation.

## Color Tokens (51)

- **Core UI (11)**: `accent`, `border`, `borderAccent`, `borderMuted`, `success`, `error`, `warning`, `muted`, `dim`, `text`, `thinkingText`
- **Backgrounds & content (11)**: `selectedBg`, `userMessageBg`, `userMessageText`, `customMessageBg`, `customMessageText`, `customMessageLabel`, `toolPendingBg`, `toolSuccessBg`, `toolErrorBg`, `toolTitle`, `toolOutput`
- **Markdown (10)**: `mdHeading`, `mdLink`, `mdLinkUrl`, `mdCode`, `mdCodeBlock`, `mdCodeBlockBorder`, `mdQuote`, `mdQuoteBorder`, `mdHr`, `mdListBullet`
- **Tool diffs (3)**: `toolDiffAdded`, `toolDiffRemoved`, `toolDiffContext`
- **Syntax (9)**: `syntaxComment`, `syntaxKeyword`, `syntaxFunction`, `syntaxVariable`, `syntaxString`, `syntaxNumber`, `syntaxType`, `syntaxOperator`, `syntaxPunctuation`
- **Thinking level borders (6 required + 1 optional)**: `thinkingOff`, `thinkingMinimal`, `thinkingLow`, `thinkingMedium`, `thinkingHigh`, `thinkingXhigh`, and optional `thinkingMax`
- **Bash mode (1)**: `bashMode`

## HTML Export (optional)

```json
{ "export": { "pageBg": "#18181e", "cardBg": "#1e1e24", "infoBg": "#3c3728" } }
```

Controls `/export` HTML output. If omitted, colors are derived from `userMessageBg`.

## Color Values

| Format | Example | Notes |
|---|---|---|
| Hex | `"#ff0000"` | 6-digit RGB |
| 256-color | `39` | xterm palette index 0–255 |
| Variable | `"primary"` | Reference to a `vars` entry |
| Default | `""` | Terminal default color |

256-color ranges: `0-15` basic ANSI (terminal-dependent), `16-231` the 6×6×6 RGB cube (`16 + 36R + 6G + B`), `232-255` grayscale.

Pi emits 24-bit RGB; older 256-color terminals get the nearest approximation. Check truecolor with `echo $COLORTERM`. In VS Code set `terminal.integrated.minimumContrastRatio` to `1` for accurate colors.

## Tips

Dark terminals want bright saturated colors with higher contrast; light terminals want darker muted colors. Start from a base palette (Nord, Gruvbox, Tokyo Night) in `vars` and reference it consistently. Test against different message types, tool states, markdown, and long wrapped text. Built-in themes to copy: `src/modes/interactive/theme/dark.json` and `light.json`.
