# Reviewer workflow

## Default execution order

1. Identify the input package.
   - Determine whether the user supplied a full manuscript, abstract-only draft, selected sections, figures, notes, or a pre-submission concept summary.
2. Build a manuscript fact base.
   - Extract the central claim, key evidence, stated significance, implied audience, and visible limitations.
3. Check assessment readiness.
   - Mark what can be assessed versus what remains missing.
   - If evidence is incomplete, preserve momentum but label uncertainty instead of blocking unless the gap is total.
4. Review the manuscript across the source-grounded axes.
   - Apply `originality`, `scientific importance`, `interdisciplinary interest`, `technical soundness`, and `readability for nonspecialists`.
5. Build an internal concern ledger.
   - Load `technical-concern-taxonomy.md` and mark each axis `applicable`, `not applicable`, or `not assessable`.
   - Give every supported concern an issue key, severity, `claim_pointer`, `evidence_pointer`, and resolution test.
   - Keep the ledger internal; expose only the fields needed to make each emitted concern traceable.
6. Generate `3` reviewer reports with different emphasis.
   - Use the same fact base for all three reports.
   - Do not invent different reviewer identities or hidden information.
   - Assign concerns from the shared ledger; do not create artificial differences merely to reduce overlap.
7. Generate a cross-review synthesis.
   - Summarize consensus, points of emphasis divergence, and the most decision-relevant technical and significance risks.
   - Treat an issue as consensus only when at least two reviewer reports independently raise the same issue key.
8. Run final QA.
   - Check evidence anchors, pairwise concern overlap, groundedness, consistency, coverage, and non-invention.

## Input handling

- Acceptable inputs include:
  - manuscript draft
  - abstract or summary paragraph
  - introduction, results, discussion, or methods excerpts
  - figure legends or selected figures
  - author notes describing the claimed contribution
- If the input is thin, the skill should still provide a bounded review, but it must clearly state the assessment boundary.

## Fact-base extraction checklist

- Extract these items before writing the reports:
  - `manuscript type or apparent submission posture`
  - `main claim`
  - `key evidence presented`
  - `claimed significance`
  - `likely interested readership from the text`
  - `visible technical gaps`
  - `readability or framing issues for nonspecialists`

## Concern-ledger fields

Use this internal shape before drafting reviewer prose:

```yaml
issue_key: experimental-design-control-selection
axis: experimental-design
applicability: applicable
severity: major
claim_pointer: The treatment effect is attributed to the intervention.
evidence_pointer: Results, "Primary outcome"; Figure 2
evidence_status: located
concern: The supplied comparison does not isolate the intervention effect.
resolution_test: Show an appropriate control or narrow the causal claim.
assigned_to: [Reviewer 1]
```

- Use section headings and supplied figure/table identifiers before page or line numbers.
- Use `location not provided` or `not assessable from supplied material` when an exact pointer cannot be verified.
- Never infer an absent figure, analysis, control, or manuscript location.

## Cross-review generation rule

- The cross-review synthesis should consolidate, not average away, reviewer differences.
- A consensus item must map to an issue key raised by at least two reviewer reports.
- Preserve consequential single-reviewer concerns under weighting differences; do not drop them merely because they lack consensus.
- It must separate:
  - shared strengths
  - shared technical concerns
  - differences in significance weighting
  - differences in readership/readability judgment

## Failure-safe behaviour

- When evidence is absent, say the case is not yet established from the supplied material.
- When significance is unclear, distinguish `potentially interesting` from `demonstrated broad importance`.
- When readability is weak, describe the barrier to nonspecialist comprehension instead of rewriting the manuscript unless asked.
