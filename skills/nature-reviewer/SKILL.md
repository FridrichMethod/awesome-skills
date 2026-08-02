---
name: nature-reviewer
description: "Simulate a Nature-style reviewer assessment from the referee perspective rather than an author rebuttal. Use when the user wants a pre-submission review, reviewer report, peer-review style critique, novelty/significance/technical soundness assessment, reviewer-style manuscript evaluation, 审稿人视角评估, 预审稿意见, or Nature reviewer report. Return 3 reviewer reports with evidence-grounded Major Concerns, Minor Comments, blocking flags, and a cross-review synthesis, grounded only in the local Nature reviewer source basis. Also trigger on general pre-submission review requests during academic writing even without the word \"Nature\", such as getting a mock peer review for any journal, critiquing a draft as a reviewer would, assessing novelty/rigor before submission, and Chinese phrasings like 审稿人视角、模拟审稿、预审、帮我审一下论文、投稿前自审、审稿意见模拟、找论文问题."
---

# Nature Reviewer Assessment Skill

Use this skill to simulate a `Nature`-style reviewer assessment package from the referee
side.

This skill is for reviewer-style manuscript evaluation, not for drafting the authors'
response. If the user wants rebuttal writing, route to `nature-response`.

## Default stance

- Ground the review only in the local source basis plus manuscript facts supplied by the user.
- Evaluate the manuscript against source-grounded axes: `originality`, `scientific importance`, `interdisciplinary readership`, `technical soundness`, and `readability for nonspecialists`.
- Use the 12-axis technical concern taxonomy only as an internal coverage checklist; it supplements but never replaces the five source-grounded axes.
- Return exactly `3 reviewer reports + 1 cross-review synthesis` unless the user explicitly asks for another structure.
- The three reviewers may differ only in `emphasis`; do not invent reviewer identities, specialties, institutions, or biographies.
- Identify who would be interested in the results and why.
- Identify technical failings that must be addressed before the authors' case is established.
- Give every substantive concern a stable ID, a faithful `claim_pointer`, and a verifiable `evidence_pointer`; mark missing locations instead of inventing them.
- Separate user-visible concerns into `Major Concerns` and `Minor Comments`. Mark a Major Concern
  `Blocking: Yes` only when the current manuscript cannot establish its central case until that
  concern is resolved; Minor Comments are never blocking.
- Do not impose a concern quota. If no grounded concern exists at a level, state that explicitly
  instead of inventing one.
- Keep the critique intellectually sharp but professionally phrased; severity comes from impact
  on the manuscript's case, not from hostile wording.
- Distinguish clearly between what is supported, what is weak, and what is not assessable from the provided material.
- When the manuscript has a clear technical domain, use claim-dependent domain gates as supporting checks, but keep the output inside the same 3-reviewer `nature-reviewer` structure.
- Do not claim the editor's final decision or certainty about fit to `Nature`.

## Accepted inputs

The skill may receive:

- full manuscript draft
- abstract, summary paragraph, or cover-summary style text
- introduction, results, discussion, or methods excerpts
- figure legends, selected figures, or result notes
- author notes in Chinese or English describing the claimed contribution
- pre-submission positioning notes

If the provided material is partial, perform a bounded review and mark the assessment boundary explicitly.

## Workflow

1. Identify the input scope and whether the job is a reviewer-style assessment rather than rebuttal drafting.
2. Extract a shared manuscript fact base: main claim, visible evidence, claimed significance, likely readership, and visible limitations.
3. Check readiness and label missing evidence or missing sections instead of inventing them.
4. Assess the manuscript using the source-grounded axes.
5. Build an internal concern ledger using `references/technical-concern-taxonomy.md`; record applicability, claim/evidence pointers, `major` or `minor` severity, a blocking flag for Major Concerns, and the resolution test for each supported concern.
6. If the manuscript clearly falls into a technical domain covered by `references/domain-specific-review-gates.md`, load only the relevant domain section and use it to sharpen the technical-soundness critique.
7. Generate `Reviewer 1`, `Reviewer 2`, and `Reviewer 3` using shared facts but different emphasis. Show separate Major Concerns and Minor Comments in each report, or explicitly say no supported concern was identified at that level. Reuse ledger issue keys internally so repeated concerns can be measured and cross-referenced.
8. Generate a `Cross-review synthesis` that separates consensus blocking concerns, other major concerns, and the minor-revision checklist. Label an issue as consensus only when at least two reviewer reports raise the same underlying concern.
9. Run QA for severity calibration, blocking calibration, evidence anchoring, overlap, groundedness, coverage, role boundaries, and non-invention.

## Output format

Unless the user asks for another format, return:

```text
Review setup
- Input scope:
- Assessment boundary:
- Shared manuscript claim summary:
- Visible evidence base:
- Missing materials affecting confidence:

Reviewer 1
- Overall assessment:
- Who would be interested in the results, and why:
- Major strengths:
- Major Concerns:
- Minor Comments:
- Technical failings that need to be addressed before the case is established:
- Assessment against Nature-style criteria:
- Recommendation posture:

For each Major Concern:
- Concern ID: R1-M1
- Severity: Major
- Blocking: Yes / No
- Axis:
- Claim pointer:
- Evidence pointer:
- Concern:
- Why it matters:
- Resolution test:

For each Minor Comment:
- Concern ID: R1-m1
- Severity: Minor
- Axis:
- Affected element:
- Evidence pointer:
- Issue:
- Required correction:

Reviewer 2
[Same structure]

Reviewer 3
[Same structure]

Cross-review synthesis
- Consensus strengths:
- Consensus blocking concerns:
- Other consensus major concerns:
- Where emphasis differs across reviewers:
- Minor revision checklist:
- Broad-interest / significance readout:
- Most important issues to resolve before a strong Nature-style case is established:

Risk / unsupported claims
- [specific unsupported or not-assessable items]
```

## Red lines

- Do not invent reviewer identities, specialty roles, or selection history.
- Do not invent experiments, validations, controls, citations, figure details, line numbers, or prior-work distinctions not present in the input.
- Do not silently turn reviewer assessment into author rebuttal drafting.
- Do not present the review as an editorial decision letter.
- Do not state that the manuscript belongs in `Nature` as a settled fact.
- Do not omit technical failings when the provided evidence does not establish the authors' case.
- Do not create Major or Minor concerns merely to fill a quota or make reviewer reports look balanced.
- Do not downgrade a core evidence, validity, ethics, or integrity problem to Minor because it is
  easy to describe, and do not upgrade a local presentation issue merely to sound severe.

## Related files

| File | Open when |
|---|---|
| [references/source-basis.md](references/source-basis.md) | You need source provenance, local rule summaries, or source-vs-implementation boundaries |
| [references/reviewer-workflow.md](references/reviewer-workflow.md) | You need the invocation order, fact-base extraction flow, or synthesis rules |
| [references/review-axes.md](references/review-axes.md) | You need the evaluation axes or reviewer weighting logic |
| [references/technical-concern-taxonomy.md](references/technical-concern-taxonomy.md) | You need the internal 12-axis coverage check, concern ledger, or claim/evidence-pointer rules |
| [references/domain-specific-review-gates.md](references/domain-specific-review-gates.md) | The manuscript has clear chemistry, engineering, materials, atmospheric, climate-ecology, hydrology, or remote-sensing evidence chains |
| [references/report-structure.md](references/report-structure.md) | You need the default output contract or section anatomy |
| [references/role-boundaries.md](references/role-boundaries.md) | You need constraints on reviewer differences and editor-versus-reviewer boundaries |
| [references/qa-checklist.md](references/qa-checklist.md) | You are finalizing an output and need groundedness / non-invention checks |
| [references/editorial criteria and processes.md](references/editorial criteria and processes.md) | You need the primary local Nature source text |

## Source hierarchy

Use sources in this order:

1. `references/editorial criteria and processes.md`
2. manuscript facts supplied by the user
3. conservative local implementation rules documented in `references/source-basis.md`
4. domain-specific supporting gates in `references/domain-specific-review-gates.md`

If a user asks for policy-level certainty beyond this local source, state the limit instead of improvising broader journal policy.
