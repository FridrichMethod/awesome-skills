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

# Multiome Pipeline - Usage Guide

## Overview

This workflow analyzes 10X Multiome data (joint scRNA-seq + scATAC-seq from the same cells) using Seurat and Signac for weighted nearest neighbor integration.

## Prerequisites

```r
install.packages(c('Seurat', 'ggplot2'))
BiocManager::install(c('Signac', 'EnsDb.Hsapiens.v86', 'BSgenome.Hsapiens.UCSC.hg38'))
```

## Quick Start

Tell your AI agent what you want to do:
- "Analyze my 10X Multiome data"
- "Integrate scRNA and scATAC from the same cells"
- "Run WNN clustering on my multiome experiment"

## Example Prompts

### Processing
> "Load my multiome Cell Ranger output"

> "Filter cells by RNA and ATAC QC metrics"

### Analysis
> "Run weighted nearest neighbors integration"

> "Find gene-peak links"

> "Compare RNA vs ATAC clustering"

## Input Requirements

| Input | Format | Description |
|-------|--------|-------------|
| Cell Ranger output | Directory | Multiome processed data |
| Fragments file | TSV.gz | ATAC fragment positions |

## What the Workflow Does

1. **Load Data** - Read RNA and ATAC from same cells
2. **RNA QC** - Standard scRNA-seq filtering
3. **ATAC QC** - TSS enrichment, nucleosome signal
4. **Process RNA** - SCTransform, PCA
5. **Process ATAC** - TF-IDF, LSI
6. **WNN** - Joint embedding
7. **Linkage** - Gene-peak correlations

## Tips

- **LSI component 1**: Often depth-correlated, skip it
- **WNN weights**: Check modality contribution per cluster
- **Gene-peak links**: Helps identify regulatory elements
- **Cell types**: Annotate using RNA markers primarily


<!-- AUTHOR_SIGNATURE: 9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE -->