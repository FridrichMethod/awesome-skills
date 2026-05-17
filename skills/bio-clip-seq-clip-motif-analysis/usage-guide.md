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

# CLIP Motif Analysis - Usage Guide

## Overview

Find enriched sequence motifs at CLIP-seq binding sites to characterize RBP binding preferences.

## Prerequisites

```bash
conda install -c bioconda homer meme bedtools
```

## Quick Start

- "Find de novo motifs at binding sites"
- "Check for known RBP motifs"

## Example Prompts

> "Run HOMER motif analysis on my CLIP peaks"

> "Find enriched 6-8mer motifs"

## What the Agent Will Do

1. Extract peak sequences (bedtools getfasta)
2. Run de novo motif discovery
3. Compare to known RBP motifs
4. Report enriched motifs

## Tips

- **Use -rna flag** for RNA motifs in HOMER
- **Background** should match GC content
- **6-8 nt motifs** are typical for RBPs


<!-- AUTHOR_SIGNATURE: 9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE -->