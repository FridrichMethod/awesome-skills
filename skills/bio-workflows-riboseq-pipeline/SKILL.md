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
name: bio-workflows-riboseq-pipeline
description: End-to-end Ribo-seq analysis from FASTQ to translation efficiency and ORF detection. Use when analyzing ribosome profiling data to study translation.
tool_type: mixed
primary_tool: Plastid
measurable_outcome: Execute skill workflow successfully with valid output within 15 minutes.
allowed-tools:
  - read_file
  - run_shell_command
---

# Ribo-seq Pipeline

## Pipeline Overview

```
FASTQ → Preprocessing → rRNA removal → Alignment → P-site → TE → ORF calling
```

## Step 1: Preprocessing

```bash
# Remove adapters
cutadapt -a CTGTAGGCACCATCAAT \
    --minimum-length 25 --maximum-length 35 \
    -o trimmed.fastq.gz reads.fastq.gz

# Remove rRNA
bowtie2 -x rRNA_index --un non_rrna.fastq.gz -U trimmed.fastq.gz
```

## Step 2: Alignment

```bash
# Align to transcriptome
STAR --genomeDir star_index \
    --readFilesIn non_rrna.fastq.gz \
    --readFilesCommand zcat \
    --outFilterMismatchNmax 2 \
    --alignEndsType EndToEnd \
    --outSAMtype BAM SortedByCoordinate
```

## Step 3: P-site Calibration

```python
from plastid import BAMGenomeArray

# Build metagene profile
metagene_generate annotation.gtf ribo.bam metagene_output/

# Calculate P-site offsets
psite annotation.gtf metagene_output/profile.txt psite_offsets.txt
```

## Step 4: Translation Efficiency

```python
# TE = Ribo-seq RPKM / RNA-seq RPKM
from plastid import BAMGenomeArray
import numpy as np

ribo_counts = count_reads(ribo_bam, genes)
rna_counts = count_reads(rna_bam, genes)
te = ribo_counts / rna_counts
```

## Step 5: ORF Detection

```bash
# RiboCode for ORF calling
RiboCode -a annotation.gtf -c config.txt -o ribocoded_orfs
```

## Related Skills

- ribo-seq/ - Individual Ribo-seq analysis skills
- differential-expression - For differential TE


<!-- AUTHOR_SIGNATURE: 9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE -->