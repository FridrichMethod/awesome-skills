# Report structure

## Default output contract

- The default output should contain these sections in order:
  1. `Review setup`
  2. `Reviewer 1`
  3. `Reviewer 2`
  4. `Reviewer 3`
  5. `Cross-review synthesis`
  6. `Risk / unsupported claims`

## Review setup

- Include:
  - `Input scope`
  - `Assessment boundary`
  - `Shared manuscript claim summary`
  - `Visible evidence base`
  - `Missing materials affecting confidence`, when applicable

## Per-reviewer structure

- Each reviewer report should use the same skeleton:
  - `Overall assessment`
  - `Who would be interested in the results, and why`
  - `Major strengths`
  - `Major concerns`
  - `Technical failings that need to be addressed before the case is established`
  - `Assessment against Nature-style criteria`
  - `Recommendation posture`
- `Assessment against Nature-style criteria` should explicitly touch:
  - `originality`
  - `scientific importance`
  - `interdisciplinary readership`
  - `technical soundness`
  - `readability for nonspecialists`
- `Recommendation posture` should stay reviewer-like, for example:
  - `supportive if technical concerns are resolved`
  - `promising but broad-interest case remains underdeveloped`
  - `currently not established from the provided evidence`

## Concern traceability

- Give each substantive concern a stable local ID: `R1-M1`, `R1-M2`, `R1-m1`, and so on.
- Use this compact shape inside `Major concerns`, `Minor concerns`, or the technical-failings block:

```text
R1-M1 — [experimental-design]
Claim pointer: [faithful one-sentence paraphrase of the challenged claim or reporting element]
Evidence pointer: [section / figure / table, or "location not provided"]
Concern: [evidence-grounded critique]
Resolution test: [evidence, analysis, clarification, or claim adjustment that would resolve it]
```

- A `claim_pointer` is not a quotation unless the exact wording was supplied.
- An `evidence_pointer` may use a page or line number only when the number was supplied or directly verified.
- Minor presentation concerns may point to the affected reporting element instead of a scientific claim.
- Do not emit the complete internal 12-axis coverage matrix.

## Cross-review synthesis structure

- Include:
  - `Consensus strengths`
  - `Consensus technical risks`
  - `Where emphasis differs across reviewers`
  - `Broad-interest / significance readout`
  - `Most important issues to resolve before a strong Nature-style case is established`
- List a concern under `Consensus technical risks` only when at least two reviewer reports raise the same underlying issue.
- Keep meaningful single-reviewer concerns visible under `Where emphasis differs across reviewers`.

## Risk / unsupported claims section

- Include explicit flags for:
  - unsupported novelty claims
  - significance claims not established by the supplied evidence
  - missing controls, validations, or comparisons
  - readability claims that cannot be assessed from the supplied excerpt
  - any place where the review necessarily relied on partial material

## Style rules

- Keep tone formal, direct, and evidence-based.
- Do not write as the authors.
- Do not write a rebuttal, action plan, or editorial decision letter unless the user explicitly asks for one.
- Do not invent line numbers, figure panels, datasets, prior studies, or missing analyses.
