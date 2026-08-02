# Keybindings

Source: https://pi.dev/docs/latest/keybindings

All shortcuts are customizable in `~/.pi/agent/keybindings.json`, which uses the same namespaced ids Pi uses internally and that extension authors pass to `keyHint()` and the injected `keybindings` manager. Pre-namespaced ids from older configs (`cursorUp`, `expandTools`, …) migrate automatically on startup. Run `/reload` after editing.

## Key Format

`modifier+key` where modifiers are `ctrl`, `shift`, `alt` (combinable, e.g. `ctrl+shift+x`, `alt+ctrl+1`). Keys:

- Letters `a-z`, digits `0-9`
- Special: `escape`/`esc`, `enter`/`return`, `tab`, `space`, `backspace`, `delete`, `insert`, `clear`, `home`, `end`, `pageUp`, `pageDown`, `up`, `down`, `left`, `right`
- Function: `f1`–`f12`
- Symbols: `` ` ``, `-`, `=`, `[`, `]`, `\`, `;`, `'`, `,`, `.`, `/`, `!`, `@`, `#`, `$`, `%`, `^`, `&`, `*`, `(`, `)`, `_`, `+`, `|`, `~`, `{`, `}`, `:`, `<`, `>`, `?`

## Actions

**`tui.editor.*` cursor** — `cursorUp` (up), `cursorDown` (down), `cursorLeft` (left, ctrl+b), `cursorRight` (right, ctrl+f), `cursorWordLeft` (alt+left, ctrl+left, alt+b), `cursorWordRight` (alt+right, ctrl+right, alt+f), `cursorLineStart` (home, ctrl+a), `cursorLineEnd` (end, ctrl+e), `jumpForward` (ctrl+]), `jumpBackward` (ctrl+alt+]), `pageUp`, `pageDown`.

**`tui.editor.*` deletion** — `deleteCharBackward` (backspace), `deleteCharForward` (delete, ctrl+d), `deleteWordBackward` (ctrl+w, alt+backspace), `deleteWordForward` (alt+d, alt+delete), `deleteToLineStart` (ctrl+u), `deleteToLineEnd` (ctrl+k).

**`tui.editor.*` kill ring** — `yank` (ctrl+y), `yankPop` (alt+y), `undo` (ctrl+-).

**`tui.input.*`** — `newLine` (shift+enter, ctrl+j), `submit` (enter), `tab` (tab), `copy` (ctrl+c).

**`tui.select.*`** — `up`, `down`, `pageUp`, `pageDown`, `confirm` (enter), `cancel` (escape, ctrl+c).

**`app.*` application** — `interrupt` (escape), `clear` (ctrl+c), `exit` (ctrl+d when editor empty), `suspend` (ctrl+z; none on Windows), `editor.external` (ctrl+g), `clipboard.pasteImage` (ctrl+v; alt+v on Windows).

**`app.session.*`** — `new`, `tree`, `fork`, `resume` (no defaults), `togglePath` (ctrl+p), `toggleSort` (ctrl+s), `toggleNamedFilter` (ctrl+n), `rename` (ctrl+r), `delete` (ctrl+d), `deleteNoninvasive` (ctrl+backspace).

**`app.model.*` / `app.thinking.*`** — `model.select` (ctrl+l), `model.cycleForward` (ctrl+p), `model.cycleBackward` (shift+ctrl+p), `thinking.cycle` (shift+tab), `thinking.toggle` (ctrl+t).

**`app.tools.*` / `app.message.*`** — `tools.expand` (ctrl+o), `message.copy` (ctrl+x), `message.followUp` (alt+enter), `message.dequeue` (alt+up).

**`app.tree.*`** — `foldOrUp` (ctrl+left, alt+left), `unfoldOrDown` (ctrl+right, alt+right), `editLabel` (shift+l), `toggleLabelTimestamp` (shift+t), `filter.default` (ctrl+d), `filter.noTools` (ctrl+t), `filter.userOnly` (ctrl+u), `filter.labeledOnly` (ctrl+l), `filter.all` (ctrl+a), `filter.cycleForward` (ctrl+o), `filter.cycleBackward` (shift+ctrl+o).

**`app.models.*`** (inside the `/scoped-models` selector) — `save` (ctrl+s), `enableAll` (ctrl+a), `clearAll` (ctrl+x), `toggleProvider` (ctrl+p), `reorderUp` (alt+up), `reorderDown` (alt+down).

## Custom Config

```json
{
  "tui.editor.cursorUp": ["up", "ctrl+p"],
  "tui.editor.cursorDown": ["down", "ctrl+n"],
  "tui.editor.deleteWordBackward": ["ctrl+w", "alt+backspace"]
}
```

Each action takes a single key or an array; user config overrides defaults. The docs include full Emacs and Vim example configs.

On native Windows, `app.suspend` has no default because Windows terminals lack Unix job control — bound manually, Pi shows a status message instead of suspending. WSL keeps normal `ctrl+z`/`fg` behavior.
