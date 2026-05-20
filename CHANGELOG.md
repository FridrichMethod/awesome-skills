# Changelog

All notable changes to this project are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) where applicable. Skill content versions are tracked upstream.

## [Unreleased]

## [0.3.1] — 2026-05-20

### Fixed
- `scripts/sync_skills.py` now sanitizes SKILL.md frontmatter so the strict Codex skill loader accepts every file:
  - **Length cap.** `description` > 1024 chars is smart-trimmed at a sentence or word boundary (4 upstream skills fixed: `tooluniverse-variant-analysis`, `tooluniverse-single-cell`, `hugging-science`, `strategist`).
  - **Mid-value colon quoting.** `key: value: with colon` is double-quoted to avoid being parsed as a nested mapping.
  - **Broken folded-scalar collapse.** Upstream typos like `description: ">"` followed by indented body lines are collapsed into a single quoted scalar honoring `>` / `>-` / `>+` / `|` / `|-` / `|+` fold semantics (~38 files: `alphafold`, `pdb`, `chai`, `boltz`, `blueprint`, …).
  - **Flow-collection passthrough.** `tags: [a, b]` and `metadata: {x: 1}` are no longer corrupted into strings; their parsed `list` / `dict` types are preserved.
  - **Multi-line quoted scalar passthrough.** A `description: "first half\n\nsecond half"` block is left intact instead of being double-wrapped.
  - **Synthesize frontmatter when missing.** Upstream `scholar-evaluation` shipped as pure markdown with no `---` block; the Codex loader was skipping it. The sanitizer now generates `---\nname: <dir>\ndescription: "..."\n---` from a heuristic over the body (preferring `## Overview` / `## Description` / `## About` / `## Summary` sections, falling back to the first paragraph or H1).
- Sanitizer is idempotent: a second `--sanitize-only` pass touches 0 files.

### Added
- `scripts/sync_skills.py --sanitize-only` CLI flag to normalize the existing `skills/` tree without running an upstream sync. Reports `sanitized`, `synthesized`, and `unrecoverable` counts.
- `_synthesize_frontmatter()` and `_extract_description_from_body()` helpers.
- `tests/test_sanitize.py` — **57 pytest cases** across smart-trim, YAML quoting helpers, end-to-end sanitization, idempotency (including a live-tree scan), post-sanitize invariants, and the three synthesis pathways (from `## Overview`, from a body paragraph, and from a dirname fallback).
- `.github/workflows/ci.yml` — runs `ruff check` + `pytest` on every push, PR, and manual dispatch.
- `pyproject.toml` — pytest and ruff configuration, dev dependency group.

### Changed
- Skill count after re-sync: 1,856 → **1,907** (+51 from upstream growth; 33 added, 121 modified, 2 deleted in the 2026-05-20 sync). All 1,907 SKILL.md files parse cleanly under `yaml.safe_load`, every `description` is ≤ 1024 chars, and Codex loads every skill including `scholar-evaluation`.

## [0.3.0] — 2026-05-17

### Added
- 5 general-purpose / foundational upstream sources added to `scripts/sync_skills.py`:
  - [obra/superpowers](https://github.com/obra/superpowers) (194.6k ⭐, 14 skills — methodology framework)
  - [anthropics/skills](https://github.com/anthropics/skills) (136.1k ⭐, 18 skills — official Anthropic)
  - [forrestchang/andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills) (133.3k ⭐, 1 skill — Karpathy CLAUDE.md)
  - [wshobson/agents](https://github.com/wshobson/agents) (35.5k ⭐, 155 skills — dev workflows)
  - [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official) (19.5k ⭐, 28 skills — official plugins)
- Net 188 new skills land via the sync workflow (213 added, 52 modified, 107 deleted by higher-priority replacements). Skill count: **1,668 → 1,856**.
- README source table grouped by scope (bio/scientific, academic, general-purpose).
- Acknowledgements section expanded with the new authors.

### Changed
- Install order in `scripts/sync_skills.py` reorganized into three tiers: bio/medical → academic → general-purpose/foundational. Higher-authority sources (Superpowers, official Anthropic, Karpathy) are now last so they win generic name collisions.
- README "Skills" badge bumped to **1800+**; "Sources" badge to **14**.

## [0.2.0] — 2026-05-17

### Added
- `install.sh` now works as a `curl … | bash` one-liner; auto-detects local clone vs remote and downloads a tarball when run remotely.
- Env overrides: `SKILLS_BRANCH`, `SKILLS_CLAUDE_DEST`, `SKILLS_CODEX_DEST`.
- Weekly GitHub Actions workflow (`.github/workflows/sync-skills.yml`) re-aggregates from all 9 upstream repos every Sunday 03:00 UTC.
- Branch ruleset on `main`: block force-push and deletion.
- Full set of community files: `LICENSE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CHANGELOG.md`, `.github/ISSUE_TEMPLATE/*`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/dependabot.yml`, `.editorconfig`, `.pre-commit-config.yaml`.

### Changed
- README rewritten with badges, table of contents, and structured awesome-list-style sections.

## [0.1.0] — 2026-05-17

### Added
- Initial commit aggregating **1668 skills** from 9 upstream sources for AI4Protein, bioinformatics, AI development, academic writing, and adjacent scientific workflows.
- Sources: K-Dense scientific-skills (137), K-Dense scientific-writer (81), GPTomics bioSkills (475), OpenClaw Medical (~868), SciAgent (199), journalism (53), Imbad academic-research (4), lishix academic-paper (2), adaptyv protein-design (21).
- `install.sh` for syncing `skills/` into `~/.claude/skills/` and `~/.codex/skills/`.

[Unreleased]: https://github.com/FridrichMethod/awesome-skills/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/FridrichMethod/awesome-skills/releases/tag/v0.3.1
[0.3.0]: https://github.com/FridrichMethod/awesome-skills/releases/tag/v0.3.0
[0.2.0]: https://github.com/FridrichMethod/awesome-skills/releases/tag/v0.2.0
[0.1.0]: https://github.com/FridrichMethod/awesome-skills/releases/tag/v0.1.0
