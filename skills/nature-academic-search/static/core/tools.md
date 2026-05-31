# MCP tools and shared modules

Multi-source literature search, citation verification, citation format conversion, and reference management via MCP tools.

## MCP tools

### Core search

| Tool | Source | Best For |
|------|--------|----------|
| `pubmed_search_articles` | PubMed MCP | Biomedical, MeSH, clinical trials |
| `search_crossref` | paper-search MCP | Cross-disciplinary, citation counts |
| `search_arxiv` | paper-search MCP | Preprints (physics, math, CS, biology) |

### Extended search

| Tool | Source | Best For |
|------|--------|----------|
| `search_google_scholar` | paper-search MCP | Broad academic search (scraped) |
| `search_semantic_scholar` | paper-search MCP | Citation graph, field-of-study filters |
| `search_biorxiv` | paper-search MCP | Biology preprints |
| `search_medrxiv` | paper-search MCP | Medical preprints |
| `search_webofscience` | paper-search MCP | Curated index, citation reports |
| `search_scopus` | paper-search MCP | Broad scholarly database |

### PubMed utilities

| Tool | Purpose |
|------|---------|
| `pubmed_fetch_articles` | Full metadata by PMID |
| `pubmed_find_related` | Related article discovery |
| `pubmed_format_citations` | APA / MLA / BibTeX / RIS formatting |
| `pubmed_convert_ids` | DOI ↔ PMID ↔ PMCID conversion |
| `pubmed_lookup_mesh` | MeSH term exploration and hierarchy |
| `pubmed_lookup_citation` | Bibliographic citation → PMID lookup |

## Shared modules

| Module | Purpose |
|--------|---------|
| [Dedup Engine](../../references/dedup-engine.md) | Unified deduplication (WFs 1, 2, 5a) |
| [Citation Parser](../../references/citation-parser.md) | Extract citations from documents (WF 2) |
| [Search Strategy](../../references/search-strategy.md) | Query construction, source selection, ranking |
| [RIS/BibTeX Format](../../references/ris-bibtex-format.md) | Format specifications and field mappings |
| [Format Converter](../../scripts/format-converter.py) | Multi-source .nbib/.ris/.bib downloader |
