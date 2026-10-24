# Contributing

Thanks for your interest in **awesome-skills**! This repo curates and re-distributes Claude Code / Codex skills from upstream projects. The day-to-day content (`skills/*`) is refreshed automatically every Sunday by a GitHub Actions workflow — most contributions are about **which upstream sources** to include, **how to filter**, and **packaging quality**.

## What we accept

| Contribution | How to submit |
|---|---|
| Add a new upstream source | Open a [skill-source issue](.github/ISSUE_TEMPLATE/new-source.yml) or PR adding it to `scripts/sync_skills.py` |
| Remove or down-prioritize an upstream | Issue or PR with rationale |
| Fix a broken skill | Issue with the skill name, what's broken, and a reproducer |
| Improve the installer | PR — see [install.sh testing](#testing-installsh) |
| Improve the sync logic | PR — see [sync script testing](#testing-the-sync-script) |
| Documentation / README polish | PR — keep the awesome-list table format consistent |

We do **not** accept direct edits to files inside `skills/`. Those get overwritten by the weekly sync. Send your fix upstream to the original repo (linked in the README) and it will flow back here.

## Adding a new upstream source

1. Open the [`new-source`](.github/ISSUE_TEMPLATE/new-source.yml) issue template.
2. Include: repo URL, star count, license, approximate skill count, focus area, and why it complements (not duplicates) existing sources.
3. If accepted, add to `UPSTREAMS` in `scripts/sync_skills.py`. The sync preserves different-content variants and records observed origins/conflicts in `library_sources.json`; source order does not authorize overwriting another origin.
4. Run `python scripts/sync_skills.py` locally and verify no LFS/large-file issues.
5. Open a PR. The workflow will run on the PR; the bot will not push from PR branches.

## Reporting a problematic skill

If a skill ships a file that breaks `git push` (LFS pointer without blob, file >40 MB, etc.) or contains questionable content:

1. Open the [`broken-skill`](.github/ISSUE_TEMPLATE/broken-skill.yml) issue.
2. Include the offending path under `skills/...`.
3. We'll either add a filter rule to `scripts/sync_skills.py` or drop the source.

## Testing the sync script

```bash
# Use an isolated worktree: this writes skills/, provenance, and README counts.
python scripts/sync_skills.py

# Check delta vs HEAD
git status --porcelain skills/ library_sources.json README.md
```

## Testing install.sh

```bash
# Static check
shellcheck install.sh

# Help text
bash install.sh --help

# Dry run against fake destinations
SKILLS_CLAUDE_DEST=/tmp/awesome-test/c \
SKILLS_CODEX_DEST=/tmp/awesome-test/x \
bash install.sh --dry-run

# Full curl pipe round-trip (only after explicitly publishing your branch)
curl -fsSL https://raw.githubusercontent.com/FridrichMethod/awesome-skills/your-branch/install.sh | SKILLS_BRANCH=your-branch bash -s -- --dry-run
```

`tests/test_git_transport.py` serves a local bare repository over `file://` (via `SKILLS_REPOSITORY_URL`) and checks the incremental transport by counting the objects each update fetches; `tests/test_bootstrap.py` runs the piped `install.sh` and, when `pwsh` is installed, `install.ps1`. After editing `skills/` by hand, regenerate the index with `python scripts/sync_skills.py --index-only`.

Run the temporary HOME contract tests and optional local Codex integration in the existing Python environment:

```bash
python -B -m pytest tests
AWESOME_SKILLS_CODEX_INTEGRATION=1 python -B -m pytest tests/test_codex_catalog.py
python -B scripts/verify_codex_catalog.py
```

The verifier starts no model turn, copies no credentials, and cleans its isolated HOME. It checks actual discovery and model-visible descriptions, not just installed files. Experimental interfaces are capability-gated; unsupported versions produce an explicit skip.

## Coding style

- Shell: pass `shellcheck -s bash -e SC2155`.
- PowerShell: keep `install.ps1` ASCII and compatible with Windows PowerShell 5.1.
- Python: pass `ruff check`. The pre-commit config covers both.
- Workflows: pass `actionlint`.
- Markdown: keep tables aligned by column.

Install hooks once with:

```bash
pip install pre-commit && pre-commit install
```

## License

By contributing you agree your contribution is licensed under the [MIT License](LICENSE). Skill content inside `skills/` retains its upstream license — see [LICENSE](LICENSE) for the note on bundled content.
