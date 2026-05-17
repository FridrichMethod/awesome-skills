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

## Quick install (no clone needed)

```bash
curl -fsSL https://raw.githubusercontent.com/FridrichMethod/awesome-skills/main/install.sh | bash
```

The installer downloads a tarball of the repo, then rsyncs `skills/` into both `~/.claude/skills/` and `~/.codex/skills/`. Nothing is left behind on disk.

### Flags

```bash
# Pass flags via `bash -s --`:
curl -fsSL https://raw.githubusercontent.com/FridrichMethod/awesome-skills/main/install.sh | bash -s -- --claude-only
curl -fsSL https://raw.githubusercontent.com/FridrichMethod/awesome-skills/main/install.sh | bash -s -- --dry-run
curl -fsSL https://raw.githubusercontent.com/FridrichMethod/awesome-skills/main/install.sh | bash -s -- --delete
```

| Flag | Effect |
|---|---|
| `--claude-only` | install only into `~/.claude/skills` |
| `--codex-only`  | install only into `~/.codex/skills` |
| `--dry-run`     | show what would change without writing |
| `--delete`      | mirror exactly — remove skills not in repo |

Env overrides: `SKILLS_BRANCH`, `SKILLS_CLAUDE_DEST`, `SKILLS_CODEX_DEST`.

### From a local clone

If you already have the repo cloned, `./install.sh` uses the local `skills/` directly and skips the download.

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
