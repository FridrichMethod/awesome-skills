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

# Automated QC Reports Usage Guide

## Overview

This guide covers generating standardized QC reports using MultiQC to aggregate metrics from multiple tools.

## Prerequisites

```bash
pip install multiqc

# Or via conda
conda install -c bioconda multiqc
```

## Quick Start

Tell your AI agent what you want to do:
- "Generate a QC report from my FastQC and alignment results"
- "Create a MultiQC report for my RNA-seq pipeline outputs"
- "Aggregate QC metrics across all samples in my project"
- "Set up automated QC reporting for my workflow"

## Example Prompts

### Basic Reports

> "Run MultiQC on my results directory and generate an HTML report"

> "Create a QC summary combining FastQC, STAR, and featureCounts outputs"

### Customization

> "Configure MultiQC to highlight samples with less than 70% mapping rate"

> "Create a MultiQC report with custom sample name cleaning"

### Integration

> "Add MultiQC report generation to my Snakemake workflow"

> "Generate a QC report comparing pre and post-filtering metrics"

## What the Agent Will Do

1. Identify QC tool outputs in the specified directory
2. Run MultiQC with appropriate configuration
3. Customize report title and sections if requested
4. Apply sample name cleaning rules
5. Generate HTML report with interactive plots

## Tips

- MultiQC auto-detects most tool outputs by filename patterns
- Use config files for reproducible report formatting
- Place config in project root as `multiqc_config.yaml`
- Custom data can be added via TSV files
- Reports are self-contained HTML (shareable without dependencies)


<!-- AUTHOR_SIGNATURE: 9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE -->