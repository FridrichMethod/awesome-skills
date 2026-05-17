<!--
# COPYRIGHT NOTICE
# This file is part of the "Universal Biomedical Skills" project.
# Copyright (c) 2026 MD BABU MIA, PhD <md.babu.mia@mssm.edu>
# All Rights Reserved.
#
# This code is proprietary and confidential.
# Unauthorized copying of this file, via any medium is strictly prohibited.
#
# Provenance: Authenticated by MD BABU MIA

-->

# Long-Read SV Pipeline - Usage Guide

## Overview

This workflow detects structural variants (deletions, insertions, inversions, duplications) from Oxford Nanopore or PacBio long-read sequencing data.

## Prerequisites

```bash
conda install -c bioconda minimap2 samtools sniffles cutesv nanoplot bcftools
```

## Quick Start

Tell your AI agent what you want to do:
- "Detect structural variants from my Nanopore data"
- "Run the long-read SV pipeline on my PacBio HiFi reads"
- "Find deletions and insertions in my ONT sequencing"

## Example Prompts

### SV calling
> "Call SVs from my aligned long reads"

> "Use Sniffles to detect structural variants"

> "Find large deletions in my sample"

### Multi-sample
> "Merge SVs across multiple samples"

> "Joint call SVs from my cohort"

## Input Requirements

| Input | Format | Description |
|-------|--------|-------------|
| Long reads | FASTQ | ONT or PacBio reads |
| Reference | FASTA | Reference genome |
| Coverage | >10x | Higher is better for SVs |

## What the Workflow Does

1. **Quality Control** - Assess read length and quality
2. **Alignment** - Map reads with minimap2
3. **SV Calling** - Detect structural variants
4. **Filtering** - Remove low-quality calls
5. **Annotation** - Add gene/clinical annotations

## Sniffles vs cuteSV

| Feature | Sniffles2 | cuteSV |
|---------|-----------|--------|
| Speed | Moderate | Fast |
| Accuracy | High | High |
| Multi-sample | Built-in | External merge |
| Best for | General use | Large cohorts |

## Tips

- **Coverage**: 15-30x recommended for reliable SV calling
- **Read length**: Longer reads detect larger SVs better
- **Tandem repeats**: Provide TR annotation to improve accuracy
- **Filtering**: Start with QUAL>=20, adjust based on validation


<!-- AUTHOR_SIGNATURE: 9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE -->