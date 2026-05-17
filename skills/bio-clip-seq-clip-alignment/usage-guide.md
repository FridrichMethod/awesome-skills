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

# CLIP-seq Alignment - Usage Guide

## Overview

Align preprocessed CLIP-seq reads to the genome optimized for crosslink site identification.

## Prerequisites

```bash
conda install -c bioconda star bowtie2 samtools
```

## Quick Start

- "Align my CLIP reads with STAR"
- "Use unique mapping only"
- "Deduplicate after alignment"

## Example Prompts

> "Align CLIP reads allowing 1 mismatch"

> "Map with bowtie2 in very-sensitive mode"

## What the Agent Will Do

1. Align reads with STAR or bowtie2
2. Filter for unique mappers
3. Sort and index BAM
4. Deduplicate with UMI tools

## Tips

- **Unique mapping** preferred for precise binding sites
- **EndToEnd** alignment prevents soft-clipping


<!-- AUTHOR_SIGNATURE: 9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE -->