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
name: bio-clip-seq-clip-alignment
description: Align CLIP-seq reads to the genome with crosslink site awareness. Use when mapping preprocessed CLIP reads for peak calling.
tool_type: cli
primary_tool: STAR
measurable_outcome: Execute skill workflow successfully with valid output within 15 minutes.
allowed-tools:
  - read_file
  - run_shell_command
---

# CLIP-seq Alignment

## STAR Alignment

```bash
STAR --runMode alignReads \
    --genomeDir STAR_index \
    --readFilesIn trimmed.fq.gz \
    --readFilesCommand zcat \
    --outFilterMultimapNmax 1 \
    --outFilterMismatchNmax 1 \
    --alignEndsType EndToEnd \
    --outSAMtype BAM SortedByCoordinate \
    --outFileNamePrefix clip_
```

## Bowtie2 Alternative

```bash
bowtie2 -x genome_index \
    -U trimmed.fq.gz \
    --very-sensitive \
    -p 8 \
    | samtools view -bS - \
    | samtools sort -o aligned.bam
```

## Post-Alignment Processing

```bash
# Index
samtools index aligned.bam

# Deduplicate with UMIs
umi_tools dedup \
    --stdin=aligned.bam \
    --stdout=deduped.bam
```

## Related Skills

- clip-preprocessing - Prepare reads
- clip-peak-calling - Call peaks


<!-- AUTHOR_SIGNATURE: 9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE -->