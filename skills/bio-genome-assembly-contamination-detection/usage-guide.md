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

# Contamination Detection - Usage Guide

## Overview

Contamination detection identifies foreign DNA in genome assemblies and assesses completeness for metagenome-assembled genomes (MAGs) and isolate assemblies.

## Prerequisites

```bash
# CheckM2
pip install checkm2
checkm2 database --download

# GUNC
conda install -c bioconda gunc
gunc download_db .

# GTDB-Tk
conda install -c bioconda gtdbtk
gtdbtk download_gtdbtk_data
```

## Quick Start

Tell your AI agent what you want to do:
- "Check my MAGs for contamination using CheckM2"
- "Classify my genomes taxonomically with GTDB-Tk"
- "Detect chimeric assemblies in my bins"

## Example Prompts

### Contamination Assessment
> "Check my MAGs for contamination using CheckM2"
> "Run CheckM2 on my genome assembly to assess completeness"
> "Detect chimeric assemblies with GUNC"

### Taxonomy Classification
> "Classify my genomes taxonomically with GTDB-Tk"
> "Assign taxonomy to my MAGs using GTDB"

### Quality Filtering
> "Filter my MAGs to keep only high-quality genomes"
> "Remove contaminating contigs from my assembly"

## What the Agent Will Do

1. Run CheckM2 to assess completeness and contamination
2. Run GUNC to detect chimeric genomes
3. Run GTDB-Tk for taxonomic assignment
4. Apply MIMAG quality thresholds
5. Flag genomes that need decontamination
6. Provide summary of genome quality statistics

## Tips

- CheckM2 is faster and more accurate than the original CheckM
- GUNC specifically detects inter-phylum chimerism missed by CheckM
- MIMAG standards: High-quality >90% complete, <5% contamination
- Combine multiple tools for comprehensive contamination assessment
- MAG quality significantly affects downstream analyses
- BlobTools can help visualize and remove contamination


<!-- AUTHOR_SIGNATURE: 9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE -->