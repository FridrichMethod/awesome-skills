# QA checklist

## Grounding checks

- Every substantive evaluation should be traceable to either:
  - `references/editorial criteria and processes.md`, or
  - manuscript facts explicitly supplied by the user.
- No reviewer persona detail should appear beyond allowed `emphasis` labels.
- No technical failing should be invented from domain habit alone when the supplied material does not show it.
- Every substantive concern has a stable concern ID, `claim_pointer`, and `evidence_pointer`.
- Page, line, figure, and table identifiers are supplied or directly verified; otherwise the pointer says `location not provided` or `not assessable from supplied material`.

## Technical coverage checks

- The internal 12-axis matrix was considered without being dumped into the final report.
- Each axis is marked internally as `applicable`, `not applicable`, or `not assessable`; absence of evidence is not silently treated as a defect.
- The technical taxonomy supplements the five source-grounded Nature axes and does not create policy claims or severity statistics.

## Coverage checks

- Confirm all three reviewer reports exist.
- Confirm the three reports differ in `emphasis` only.
- Confirm each reviewer still addresses all core axes, even if briefly.
- Confirm a `Cross-review synthesis` section exists.
- Confirm a `Risk / unsupported claims` section exists.

## Boundary checks

- Confirm the output stays in reviewer-assessment mode, not author-response mode.
- Confirm the output does not claim a final editorial decision.
- Confirm broad-interest judgment is expressed cautiously, because the source assigns that final judgment to editors.

## Non-invention checks

- No invented reviewer identity, specialty, institution, or selection history.
- No invented experiments, controls, analyses, line numbers, citations, prior-work details, or figure-specific content absent from the input.
- If evidence is partial, mark `AUTHOR_INPUT_NEEDED` or `Not assessable from provided material`.

## Consistency checks

- Shared manuscript facts should stay consistent across all three reviewers.
- Divergence across reviewers should reflect weighting differences, not contradictory factual claims.
- Technical failings listed in the synthesis should match issues already raised in at least one individual report.
- Consensus issues were raised by at least two reviewer reports and map to the same underlying issue key.
- Preserve important single-reviewer concerns as weighting differences instead of deleting them.

## Overlap checks

- Normalize concerns to internal issue keys before comparing reviewer reports.
- For each reviewer pair, calculate the duplicate share as `shared issue keys / smaller report issue count`; target less than `35%`.
- If overlap exceeds the target, remove redundant prose, cross-reference truly shared concerns, or redistribute emphasis.
- Treat `35%` as a redundancy target, not a reason to invent diversity. A short manuscript with only a few supportable issues may exceed it if the limitation is stated explicitly.

## Final release rule

- If the skill cannot produce a grounded three-reviewer package without major invention, it should return a bounded draft review with explicit missing-information flags rather than pretending certainty.
