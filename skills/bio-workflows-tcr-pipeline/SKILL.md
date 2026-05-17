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

---
name: bio-workflows-tcr-pipeline
description: End-to-end TCR/BCR repertoire analysis from FASTQ to clonotype diversity metrics. Use when analyzing immune repertoire sequencing data from bulk or single-cell experiments.
tool_type: cli
primary_tool: MiXCR
measurable_outcome: Execute skill workflow successfully with valid output within 15 minutes.
allowed-tools:
  - read_file
  - run_shell_command
---

# TCR/BCR Analysis Pipeline

## Pipeline Overview

```
FASTQ → MiXCR align → Assemble → Export → VDJtools diversity → Visualization
```

## Step 1: MiXCR Processing

```bash
# Align reads to V(D)J segments
mixcr align -s hsa -p rna-seq \
    R1.fastq.gz R2.fastq.gz \
    aligned.vdjca

# Assemble clonotypes
mixcr assemble aligned.vdjca clones.clns

# Export
mixcr exportClones clones.clns clones.txt
```

## Step 2: VDJtools Analysis

```bash
# Convert to VDJtools format
vdjtools Convert -S mixcr clones.txt vdjtools/

# Diversity metrics
vdjtools CalcDiversityStats vdjtools/clones.txt diversity/

# Sample overlap
vdjtools CalcPairwiseDistances vdjtools/*.txt overlap/
```

## Step 3: Visualization

```bash
# Spectratype plot
vdjtools PlotFancySpectratype vdjtools/clones.txt spectra/

# V usage
vdjtools PlotFancyVJUsage vdjtools/clones.txt usage/
```

## QC Checkpoints

1. **After alignment**: Check V/J assignment rate (>70% typical)
2. **After assembly**: Verify clonotype count and coverage
3. **After diversity**: Compare metrics to expected range

## Related Skills

- tcr-bcr-analysis/mixcr-analysis - Detailed MiXCR usage
- tcr-bcr-analysis/vdjtools-analysis - Diversity metrics
- tcr-bcr-analysis/repertoire-visualization - Plots


<!-- AUTHOR_SIGNATURE: 9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE -->