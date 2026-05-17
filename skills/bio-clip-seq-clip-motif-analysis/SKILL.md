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
name: bio-clip-seq-clip-motif-analysis
description: Identify enriched sequence motifs at CLIP-seq binding sites for RBP binding specificity. Use when characterizing the sequence preferences of an RNA-binding protein.
tool_type: cli
primary_tool: HOMER
measurable_outcome: Execute skill workflow successfully with valid output within 15 minutes.
allowed-tools:
  - read_file
  - run_shell_command
---

# CLIP Motif Analysis

## HOMER De Novo Motifs

```bash
# Extract sequences from peaks
bedtools getfasta -fi genome.fa -bed peaks.bed -fo peaks.fa

# Find enriched motifs
findMotifs.pl peaks.fa fasta output_dir \
    -len 6,7,8 \
    -rna
```

## MEME-ChIP

```bash
meme-chip -oc output_dir \
    -dna \
    peaks.fa
```

## Known Motif Enrichment

```bash
# HOMER known motif scan
findMotifs.pl peaks.fa fasta output_dir \
    -rna \
    -known
```

## Related Skills

- clip-peak-calling - Get peaks
- chip-seq/motif-analysis - General motif concepts


<!-- AUTHOR_SIGNATURE: 9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE -->