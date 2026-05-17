# Security Policy

## Reporting a vulnerability

For vulnerabilities in **this repo's own code** (the installer, sync script, and workflows in `/`, `/scripts/`, `/.github/`):

1. Prefer GitHub Security Advisories: https://github.com/FridrichMethod/awesome-skills/security/advisories/new
2. Or open a private issue tagged `security` and the maintainer will reply within 7 days.

Please do **not** open a public issue for an exploitable vulnerability in the installer or workflows.

## Skill content vulnerabilities

The `skills/` directory aggregates content from upstream repositories listed in the [README](README.md#sources). Each skill's `references/`, `repo/`, or `examples/` subtree may include dependency manifests (`requirements.txt`, `package.json`, etc.) inherited from upstream. **These are not maintained here.**

GitHub Dependabot will flag vulnerabilities against those manifests. We do not action them in this repo because:

1. The manifests are bundled documentation, not actively installed dependencies.
2. Fixing them here is overwritten by the weekly sync.
3. The right fix is upstream — file an issue against the source repo.

If you find a genuinely exploitable issue in a skill's code (not a transitive-dep CVE):

1. File against the upstream source linked in the README.
2. Optionally, file an issue here so we can temporarily filter the path in `scripts/sync_skills.py`.

## Supply chain

- `install.sh` fetches the repo tarball over HTTPS from `github.com/FridrichMethod/awesome-skills`.
- The sync workflow uses pinned major versions of `actions/checkout` and `actions/setup-python`.
- Pre-commit hooks are pinned in `.pre-commit-config.yaml`.

## Acknowledgements

This policy is intentionally lightweight to match the curation-only scope of the project. Material vulnerabilities will be credited in the [CHANGELOG](CHANGELOG.md).
