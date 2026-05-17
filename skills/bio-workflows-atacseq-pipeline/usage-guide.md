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

# ATAC-seq Pipeline - Usage Guide

## Overview

This workflow processes ATAC-seq data from raw FASTQ files to accessibility peaks, with optional differential analysis and transcription factor footprinting.

## Prerequisites

```bash
# CLI tools
conda install -c bioconda fastp bowtie2 samtools macs3 deeptools bedtools tobias

# R packages
BiocManager::install(c('DiffBind', 'ChIPseeker'))
```

## Quick Start

Tell your AI agent what you want to do:
- "Run the ATAC-seq pipeline on my samples"
- "Call accessibility peaks from my ATAC-seq data"
- "Find differential accessibility between treatment and control"

## Example Prompts

### Starting from FASTQ
> "Process my ATAC-seq FASTQ files through peak calling"

> "Run ATAC-seq analysis on human samples"

> "I have paired-end ATAC-seq, align and call peaks"

### Analysis
> "Calculate TSS enrichment for my ATAC-seq"

> "Find differential peaks between conditions"

> "Run TF footprinting with TOBIAS"

## Input Requirements

| Input | Format | Description |
|-------|--------|-------------|
| FASTQ files | .fastq.gz | Paired-end reads |
| Reference | FASTA | Reference genome + Bowtie2 index |
| Motifs (optional) | JASPAR | For footprinting analysis |

## What the Workflow Does

1. **Quality Control** - Trim Nextera adapters
2. **Alignment** - Map reads with Bowtie2
3. **BAM Processing** - Remove chrM, shift for Tn5, deduplicate
4. **Peak Calling** - Call accessible regions with MACS3
5. **QC** - TSS enrichment, FRiP, fragment sizes
6. **Differential** - Compare accessibility between conditions
7. **Footprinting** - Infer TF binding from accessibility patterns

## ATAC-seq vs ChIP-seq Processing

| Aspect | ATAC-seq | ChIP-seq |
|--------|----------|----------|
| Adapters | Nextera | TruSeq |
| Control | None needed | Input required |
| Tn5 shift | Yes (+4/-5 bp) | No |
| chrM | High, remove | Low |
| Peak type | Narrow | Narrow or broad |

## Tips

- **Mitochondrial**: Expect 20-50% chrM reads; always filter
- **Tn5 shift**: Essential for accurate footprinting
- **TSS enrichment**: Good library shows >5 enrichment
- **Fragment sizes**: Should show nucleosome-free and nucleosome peaks
- **Footprinting**: Requires high depth (>50M reads)


<!-- AUTHOR_SIGNATURE: 9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE -->