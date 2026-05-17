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

# Batch Downloads - Usage Guide

## Overview

This skill enables AI agents to help you download large numbers of records from NCBI efficiently, using the history server, proper batching, and rate limiting.

## Prerequisites

```bash
pip install biopython
```

Optional but recommended for large downloads:
- NCBI API key from https://www.ncbi.nlm.nih.gov/account/settings/

## Quick Start

Tell your AI agent what you want to do:

- "Download all human insulin mRNA sequences from GenBank"
- "Fetch these 500 protein sequences and save to a FASTA file"
- "Download all PubMed abstracts for CRISPR papers from 2024"
- "Get GenBank records for all mouse mitochondrial genes"

## Example Prompts

### Search and Download
> "Download all FASTA sequences matching 'human AND BRCA1 AND mRNA' from nucleotide"

### Download by ID List
> "I have a list of 1000 accession numbers in ids.txt - download them all as FASTA"

### Large Datasets
> "Download all RefSeq proteins for E. coli K-12 (this will be thousands of records)"

### Specific Formats
> "Download GenBank format (with annotations) for all human TP53 transcript variants"

## What the Agent Will Do

1. Set up Entrez with email (and API key if available)
2. Use the history server for large result sets
3. Download in appropriate batch sizes
4. Add delays between requests to respect rate limits
5. Include retry logic for reliability
6. Save to the specified output file

## Tips

- Provide your NCBI API key if you have one (10x faster)
- Specify the output format (FASTA, GenBank, etc.)
- Mention approximate result size if known
- For very large downloads (>100,000), consider running overnight
- Results are saved to file, not loaded into memory


<!-- AUTHOR_SIGNATURE: 9a7f3c2e-MD-BABU-MIA-2026-MSSM-SECURE -->