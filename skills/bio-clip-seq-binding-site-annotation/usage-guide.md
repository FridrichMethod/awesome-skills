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

# Binding Site Annotation - Usage Guide

## Overview

Annotate CLIP-seq peaks to genomic features like UTRs, CDS, and introns.

## Prerequisites

```r
BiocManager::install(c('ChIPseeker', 'TxDb.Hsapiens.UCSC.hg38.knownGene'))
```

## Quick Start

- "Annotate peaks to transcript features"
- "What fraction of peaks are in 3'UTRs?"

## Example Prompts

> "Annotate my CLIP peaks with ChIPseeker"

> "Show distribution across UTRs, CDS, introns"

## What the Agent Will Do

1. Load peaks and annotation
2. Assign peaks to features
3. Create summary pie chart

## Tips

- **3'UTR enrichment** common for mRNA stability regulators
- **Intron enrichment** common for splicing factors


<!-- AUTHOR_SIGNATURE: 9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE -->