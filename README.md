# awesome-skills

Personal sync repo of **1668 agent skills** for Claude Code and Codex CLI, curated for AI4Protein, bioinformatics, AI development, academic writing, and adjacent scientific workflows.

## What's inside

The `skills/` directory holds one folder per skill, each containing a `SKILL.md` file (plus any references/scripts). Skills are aggregated from these sources — credit to the original authors:

| Source | Stars | Skills | Focus |
|---|---:|---:|---|
| [K-Dense-AI/claude-scientific-skills](https://github.com/K-Dense-AI/claude-scientific-skills) | 23.4k | ~137 | Scientific computing, bioinformatics, cheminformatics |
| [K-Dense-AI/claude-scientific-writer](https://github.com/K-Dense-AI/claude-scientific-writer) | 1.8k | ~81 | Scientific writing, citations, posters |
| [FreedomIntelligence/OpenClaw-Medical-Skills](https://github.com/FreedomIntelligence/OpenClaw-Medical-Skills) | 2.5k | ~868 | Medical AI, clinical genomics, drug discovery |
| [GPTomics/bioSkills](https://github.com/GPTomics/bioSkills) | 667 | ~475 | Bioinformatics (variant, CRISPR, single-cell, spatial) |
| [jaechang-hits/SciAgent-Skills](https://github.com/jaechang-hits/SciAgent-Skills) | 158 | 199 | Life-science workflows (BixBench 92%) |
| [adaptyvbio/protein-design-skills](https://github.com/adaptyvbio/protein-design-skills) | 127 | 21 | **Protein design pipeline**: BoltzGen, Chai, RFdiffusion, ProteinMPNN |
| [Imbad0202/academic-research-skills](https://github.com/Imbad0202/academic-research-skills) | 8.6k | 4 | Academic research→write→review pipeline |
| [lishix520/academic-paper-skills](https://github.com/lishix520/academic-paper-skills) | 624 | 2 | Paper strategist + composer |
| [jamditis/claude-skills-journalism](https://github.com/jamditis/claude-skills-journalism) | 209 | 53 | Journalism, FOIA, fact-checking, academic writing |

On name collision, later sources in the install order overwrite earlier ones; the priority order places specialized protein-design and academic skills last so they win conflicts.

## Quick install — one-line, no clone needed

```bash
curl -fsSL https://raw.githubusercontent.com/FridrichMethod/awesome-skills/main/install.sh | bash
```

The installer downloads a tarball of the repo to a tempdir, rsyncs `skills/` into both `~/.claude/skills/` and `~/.codex/skills/`, then cleans up. Nothing is left behind on disk.

**Requirements on the target machine:** `bash`, `curl`, `tar`, `rsync`. All four are standard on macOS and most Linux distros. On a fresh Debian/Ubuntu, install with `sudo apt-get install -y rsync` if rsync is missing.

### Flags

```bash
# Pass flags via `bash -s --`:
curl -fsSL https://raw.githubusercontent.com/FridrichMethod/awesome-skills/main/install.sh \
  | bash -s -- --claude-only
```

| Flag | Effect |
|---|---|
| `--claude-only` | install only into `~/.claude/skills` |
| `--codex-only`  | install only into `~/.codex/skills` |
| `--dry-run`     | preview what would change without writing |
| `--delete`      | mirror exactly — remove local skills not in the repo |
| `-h`, `--help`  | print usage |

### Env overrides

| Variable | Default | Effect |
|---|---|---|
| `SKILLS_BRANCH` | `main` | install from a different branch |
| `SKILLS_CLAUDE_DEST` | `$HOME/.claude/skills` | override Claude install path |
| `SKILLS_CODEX_DEST` | `$HOME/.codex/skills` | override Codex install path |

**Important:** when using `curl … | bash`, env vars must be set on `bash`, not on `curl`. Either export first or place them on the pipe's right side:

```bash
# ✓ works
export SKILLS_CLAUDE_DEST=/custom/claude
curl -fsSL .../install.sh | bash

# ✓ also works
curl -fsSL .../install.sh | SKILLS_CLAUDE_DEST=/custom/claude bash

# ✗ silently ignored — only curl sees the var
SKILLS_CLAUDE_DEST=/custom/claude curl -fsSL .../install.sh | bash
```

### Common recipes

```bash
# Preview only — no files written
curl -fsSL https://raw.githubusercontent.com/FridrichMethod/awesome-skills/main/install.sh \
  | bash -s -- --dry-run

# Mirror exactly (remove local skills that aren't in the repo)
curl -fsSL https://raw.githubusercontent.com/FridrichMethod/awesome-skills/main/install.sh \
  | bash -s -- --delete

# Install only Codex skills, into a custom dir
export SKILLS_CODEX_DEST=/opt/agents/codex/skills
curl -fsSL https://raw.githubusercontent.com/FridrichMethod/awesome-skills/main/install.sh \
  | bash -s -- --codex-only

# Pin to a specific branch (or tag)
export SKILLS_BRANCH=main
curl -fsSL "https://raw.githubusercontent.com/FridrichMethod/awesome-skills/${SKILLS_BRANCH}/install.sh" \
  | bash
```

### Re-syncing later

The same one-liner is idempotent — re-run it any time to refresh your local skills from the latest `main`. Add `--delete` if you want exact mirror semantics.

```bash
# Drop into a cron or a shell alias for periodic sync
alias sync-skills='curl -fsSL https://raw.githubusercontent.com/FridrichMethod/awesome-skills/main/install.sh | bash'
```

### From a local clone (rare)

If you happen to have the repo cloned, `./install.sh` detects the adjacent `skills/` directory and uses it directly without re-downloading.

## Highlights for AI4Protein

- **Generation/design**: `boltzgen`, `rfdiffusion`, `proteinmpnn`, `ligandmpnn`, `solublempnn`, `bindcraft`, `binder-design`, `generative-design`
- **Structure prediction**: `alphafold`, `alphafold-predictions`, `chai`, `boltz`, `foldseek`, `modern-structure-prediction`, `protein-structure-prediction`
- **Language models**: `esm`, `esm-protein-language-model`
- **QC / validation**: `protein-qc`, `pose-validation`, `protein-design-workflow`, `binding-characterization`
- **Antibody / therapeutics**: `antibody-design-agent`, `mage-antibody-generator`, `tooluniverse-antibody-engineering`, `tooluniverse-protein-therapeutic-design`
- **Databases**: `uniprot-database`, `alphafold-database`, `pdb-database`, `chembl-database`, `drugbank-database`, `interpro-database`, `pubchem-database`

## Highlights for journal / paper writing

- **Pipelines**: `academic-paper`, `academic-paper-reviewer`, `academic-pipeline`, `deep-research-swarm`, `composer`, `strategist`
- **Drafting**: `scientific-writing`, `scientific-manuscript-writing`, `academic-writing`, `article-writing`, `peer-review-methodology`
- **Citation / lit search**: `pubmed-database`, `biorxiv-database`, `medrxiv-search`, `literature-review`, `citation-management`, `paperzilla`
- **Figures**: `latex-posters`, `latex-research-posters`, `scientific-schematics`, `scientific-visualization`, `markdown-mermaid-writing`, `pptx-posters`
- **Venue figure guides**: `nature-figure-guide`, `cell-figure-guide`, `science-figure-guide`, `lancet-figure-guide`, `nejm-figure-guide`, `pnas-figure-guide`, `elife-figure-guide`, `cancer-research-figure-guide`

## Licensing

Each upstream repo retains its own license. Review individual `SKILL.md` files and source repos before using a skill commercially.

## Update workflow

**Automated:** A GitHub Actions workflow (`.github/workflows/sync-skills.yml`) runs every Sunday 03:00 UTC. It re-clones each upstream repo, copies skill roots into `skills/` (last-source-wins on conflict), filters out LFS pointers / large binaries, and pushes a commit if anything changed. Trigger manually via the **Actions** tab → *sync-skills* → *Run workflow*.

**Local sync between machines:**

```bash
git pull && ./install.sh
```

**Manual aggregation locally** (same logic as the workflow):

```bash
python scripts/sync_skills.py
```
