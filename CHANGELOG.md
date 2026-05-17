# Changelog

All notable changes to this project are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) where applicable. Skill content versions are tracked upstream.

## [Unreleased]

### Added
- 5 general-purpose / foundational upstream sources added to `scripts/sync_skills.py`:
  - [obra/superpowers](https://github.com/obra/superpowers) (194.6k ⭐, 14 skills — methodology framework)
  - [anthropics/skills](https://github.com/anthropics/skills) (136.1k ⭐, 18 skills — official Anthropic)
  - [forrestchang/andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills) (133.3k ⭐, 1 skill — Karpathy CLAUDE.md)
  - [wshobson/agents](https://github.com/wshobson/agents) (35.5k ⭐, 155 skills — dev workflows)
  - [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official) (19.5k ⭐, 28 skills — official plugins)
- README source table now grouped by scope (bio/scientific, academic, general-purpose).
- Acknowledgements section expanded with the new authors.

### Changed
- Install order in `scripts/sync_skills.py` reorganized into three tiers: bio/medical → academic → general-purpose/foundational. Higher-authority sources (Superpowers, official Anthropic, Karpathy) are now last so they win generic name collisions.

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

[Unreleased]: https://github.com/FridrichMethod/awesome-skills/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/FridrichMethod/awesome-skills/releases/tag/v0.2.0
[0.1.0]: https://github.com/FridrichMethod/awesome-skills/releases/tag/v0.1.0
