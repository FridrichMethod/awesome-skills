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

# Interactive Visualization - Usage Guide

## Overview
Interactive plots enable exploration of large datasets through zooming, panning, and hover tooltips. Export as standalone HTML files for sharing.

## Prerequisites
```bash
# Python
pip install plotly bokeh

# R
install.packages('plotly')
```

## Quick Start
Tell your AI agent what you want to do:
- "Create an interactive volcano plot with gene hover labels"
- "Make a zoomable PCA plot colored by condition"
- "Convert my ggplot to interactive plotly"

## Example Prompts
### Interactive Exploration
> "Create an interactive scatter plot where I can hover to see sample names"

> "Make a zoomable plot of my expression data"

### Conversion from Static
> "Convert my ggplot volcano plot to interactive"

> "Add hover tooltips to my PCA plot"

### Sharing
> "Export my interactive plot as a standalone HTML file"

> "Create an interactive heatmap I can share with collaborators"

## What the Agent Will Do
1. Prepare data with appropriate hover text columns
2. Create interactive plot with plotly or bokeh
3. Configure hover tooltips with relevant metadata
4. Enable zoom, pan, and selection tools
5. Export as standalone HTML for sharing

## Tool Selection

| Tool | Language | Best For |
|------|----------|----------|
| plotly | Python/R | General interactive plots, ggplot2 conversion |
| bokeh | Python | Web apps, linked brushing, widgets |

## Tips
- Include gene names and metadata in hover tooltips
- Use `ggplotly()` to convert existing ggplot2 plots
- Export as HTML for easy sharing (no server needed)
- Consider file size for large datasets (downsample if needed)

## Related Skills
- **data-visualization/ggplot2-fundamentals** - Static versions
- **reporting/quarto-reports** - Embed in documents


<!-- AUTHOR_SIGNATURE: 9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE -->