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
name: bio-clip-seq-binding-site-annotation
description: Annotate CLIP-seq binding sites to genomic features including 3'UTR, 5'UTR, CDS, introns, and ncRNAs. Use when characterizing where an RBP binds in transcripts.
tool_type: mixed
primary_tool: ChIPseeker
measurable_outcome: Execute skill workflow successfully with valid output within 15 minutes.
allowed-tools:
  - read_file
  - run_shell_command
---

# Binding Site Annotation

## Using ChIPseeker (R)

```r
library(ChIPseeker)
library(TxDb.Hsapiens.UCSC.hg38.knownGene)

txdb <- TxDb.Hsapiens.UCSC.hg38.knownGene

peaks <- readPeakFile('peaks.bed')
anno <- annotatePeak(peaks, TxDb = txdb)

plotAnnoPie(anno)
```

## Using BEDTools

```bash
# Annotate to UTRs
bedtools intersect -a peaks.bed -b 3utr.bed -wa -wb > peaks_3utr.bed
```

## Python Annotation

```python
import pandas as pd

def annotate_peaks(peaks_bed, annotation_gtf):
    '''Annotate peaks to genomic features'''
    # Load peaks and annotations
    # Intersect and categorize
    pass
```

## Related Skills

- clip-peak-calling - Get peaks
- genome-intervals/interval-arithmetic - Intersect peaks with genomic features


<!-- AUTHOR_SIGNATURE: 9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE -->