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

# Modification Visualization - Usage Guide

## Overview

Visualize RNA modification patterns with metagene plots, heatmaps, and browser tracks.

## Prerequisites

```r
BiocManager::install(c('Guitar', 'TxDb.Hsapiens.UCSC.hg38.knownGene', 'ComplexHeatmap'))
```

```bash
conda install -c bioconda deeptools ucsc-bedtobigbed
```

## Quick Start

- "Create metagene plot of m6A around stop codons"
- "Make browser tracks from my MeRIP data"
- "Visualize m6A distribution across transcripts"

## Example Prompts

### Metagene Plots

> "Plot m6A distribution relative to UTRs and CDS"

> "Create Guitar metagene plot from my peaks"

### Browser Tracks

> "Generate bigWig tracks for IGV"

> "Make normalized coverage tracks from IP and input"

### Heatmaps

> "Create heatmap of m6A signal around peak centers"

> "Cluster m6A peaks by signal pattern"

## What the Agent Will Do

1. Load m6A peaks or signal data
2. Generate metagene profile around features
3. Create normalized browser tracks
4. Build signal heatmaps if requested
5. Export publication-ready figures

## Tips

- **Guitar** - Best for transcript-centric metagene plots
- **deepTools** - Flexible for custom feature sets
- **Stop codon enrichment** - Classic m6A pattern (enriched near stop)
- **Normalize** - Use CPM or RPKM for comparable tracks
- **IGV/UCSC** - bigWig format for genome browsers


<!-- AUTHOR_SIGNATURE: 9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE -->