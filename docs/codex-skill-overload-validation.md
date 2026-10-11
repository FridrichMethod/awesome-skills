# Codex skill overload validation

Measured on 2026-10-11 with codex-cli 0.162.1; these are observations, not installer limits or version pins.

The live inventory was read only: 2119 top-level Codex entries, 2117 with SKILL.md.
The repository supplied 2120 top-level skill documents and 4479 directories for an isolated legacy fixture. This fixture copies repository SKILL.md documents and directory layout; it does not copy credentials or supporting data from HOME. Sherlock and Microsoft Foundry fixtures are generated locally, with Sherlock exposed through a symlink in the temporary .agents/skills directory.

| Stage | Discovery | Model-visible | With description | Traversal limit |
|---|---:|---:|---:|---|
| Legacy full fixture | 2006 | 287 | 0 | yes |
| Larger-budget legacy fixture | 2006 | 493 | 0 | yes |
| Migrated default | 8 | 7 | 7 | no |
| No-argument updater | 8 | 7 | 7 | no |

Sherlock and Foundry were discovered, with descriptions, before migration but omitted from model input. Both appeared with their descriptions after migration and after a genuinely argument-free install.sh updater run. That run preserved selection and proposed zero Codex actions. Discovery has one more system skill than prompt preview because this Codex version intentionally hides review-agent.

A separate temporary HOME smoke test copied and fingerprint-verified all 2120 complete repository trees, including supporting files, in the cache. Selectively enabling protein-design-workflow produced discovery 7 / model-visible 6, with all six descriptions retained; its actual repository description was checked in prompt input. A repeat update retained the selection and Claude had all 2120 library directories. This smoke test has no Sherlock/Foundry fixtures, so its counts differ from the comparison above.

Validation: 137 tests passed, including the enabled local Codex integration; ruff check, formatting checks for new code, shellcheck, workflow YAML parsing, and git diff whitespace checks passed. actionlint was unavailable. Tests cover first install, exact legacy adoption, support-file/permission modifications, unknown entries, symlinks, .system and protected names, independent clients/destinations, identical/different names, generated-router collisions, zero-write local/remote dry-run, restore and path validation, interrupted preparation, cross-filesystem rejection, concurrent installer rejection, cache integrity, and no-argument updates.

Reproduce in an existing Python environment containing pytest and PyYAML:

```bash
AWESOME_SKILLS_CODEX_INTEGRATION=1 python -B -m pytest tests
python -B scripts/verify_codex_catalog.py --compare-budget 200000
ruff check scripts tests
shellcheck install.sh
```

The verifier detects the local version, help/features, and generated skills/list protocol schema. It invokes no model and uses no live client configuration. An early exploratory bare app-server startup attempted anonymous featured-plugin cache requests and returned 401; the delivered verifier disables plugins/apps/remote_plugin for discovery and preview, strips authentication environment variables, and routes proxies to a closed loopback port. Experimental interface changes result in an explicit skip or validation failure, not a file-only success.

The real HOME has not been migrated, and no Sherlock connection, dotfiles modification, or push was performed. Exact legacy content differing from the available repository snapshot remains protected; consequently a real migration can preserve more skills than this controlled fixture. Pre-manifest installation history and variants lost by the former last-source-wins policy cannot be reconstructed. Backups and cache generations are deliberately retained for recovery; custom destinations need the state directory on the same filesystem. External plugins/user collections can independently overload Codex. Test HOME and catalog-probe artifacts were removed; the review JSON and any real-HOME dry-run plan are retained as reviewable outputs.
