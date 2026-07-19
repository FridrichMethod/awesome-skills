# `nature-citation` Skill

[中文说明](README.md)

`nature-citation` splits manuscript passages or scientific claims into citable units and finds supporting references from Nature Portfolio, the Science family, and Cell Press.

## What To Use It For

- Add citations to key claims in an introduction, discussion, or reviewer response.
- Split long passages into stable claim units such as `S001` and `S002`.
- Restrict evidence to Nature, Science, Cell, and their subjournals, or keep only flagship journals.
- Explain each candidate paper's support position, evidence strength, and insertion point.
- Export selected references for Zotero, EndNote, or other reference managers.

## Typical Requests

- "Split this introduction paragraph and add Nature-series citations."
- "Use only CNS and subjournal papers from the last five years to support these claims."
- "I have confirmed these DOIs; export them in a Zotero-importable format."

## What You Need To Provide

- Passage to cite, claim list, or DOI list.
- Journal scope, year range, whether reviews are allowed, and whether only flagship journals should be kept.
- Target citation style and export format such as `RIS`, `ENW`, or Zotero `RDF`.

## Outputs

- Claim-segmentation table and candidate-reference table.
- Suggested insertion position, DOI, journal, year, and support note for each claim.
- Optional JSON, TSV, Markdown, or HTML review materials.
- Reference-management export file.

## Boundaries

- Candidate papers are support options, not a guarantee that the final citation is appropriate.
- Blogs, press releases, and search snippets are not used as sole evidence.
- When a paper supports a nearby but not identical claim, the evidence mismatch is stated explicitly.

## Related Skills

- `nature-academic-search`: broader literature search and citation-metric audits.
- `nature-ref-verifier`: verify selected reference metadata.
- `nature-writing`: integrate citation choices back into manuscript argument.
