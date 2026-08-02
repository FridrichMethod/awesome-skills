# Workflow and output format

## Accepted inputs

The skill may receive: pasted editorial decision or revision-invitation email; editor decision letter; reviewer comments; previous response draft; manuscript change notes; tracked-change summary; line or page numbers; figure, table, and supplement list; author notes in Chinese or English; journal name and article type; manuscript title; author list; manuscript ID; original manuscript text or LaTeX source; requested cover-letter or LaTeX output format.

If reviewer boundaries or comment segmentation are ambiguous, flag the ambiguity instead of inventing reviewer structure.

## Decision-type gate and revision strategy

For normal revision-response work, determine the editorial decision before drafting the response
strategy or response prose:

1. Use an explicit label in the editor decision letter or revision invitation when supplied.
2. Normalize informal author wording such as `major review` and `minor review` to `Major Revision`
   and `Minor Revision` when the meaning is unambiguous.
3. If the decision remains unclear, ask one concise question in the user's language and pause:
   `这是 Major Revision（大修）还是 Minor Revision（小修）？如果决定信没有明确写，请把决定信发给我，我帮你判断。`
   English default: `Is this a Major Revision or a Minor Revision? If the decision letter does
   not state it clearly, please send it and I can help classify the decision.`
4. Do not infer the decision type from comment count, reviewer tone, requested workload, or the
   apparent severity of individual comments.

After the gate is resolved, use the corresponding default strategy:

| Decision type | Default revision strategy |
|---|---|
| `Major Revision` | Build an evidence-first work plan. Prioritize central-claim support, experiments or analyses, methods and statistics, validation, figures, limitations, and any structural rewriting. Treat unresolved central evidence or integrity/compliance items as finalization blockers. Responses should explain both the action and the evidence that resolves each concern. |
| `Minor Revision` | Use a bounded correction plan. Prioritize precise wording, definitions, citations, reporting details, figure/table presentation, and localized clarifications. Keep replies concise and avoid unnecessary redesign of the study or expansion of claims unless an editor or reviewer request genuinely requires it. |

The decision label sets the package-level posture, not the severity of every comment. A substantive
evidence, statistics, ethics, or data-integrity concern remains major or blocking even inside a
Minor Revision. Journal instructions and explicit editor directions override these defaults.

## Workflow

1. Identify task mode and input readiness: `draft`, `audit`, `revise`, `triage-only`, `cover-letter`, `revision-package`, `latex-template`, or `appeal-like`.
2. If the input is a pasted journal email, automatically extract manuscript title, manuscript ID, journal, decision type, editor instructions, reviewer-report boundaries, required revision files, deadline, and portal-specific constraints before drafting.
3. Pass the decision-type gate. For normal revision modes, pause and ask the user when the decision remains unclear; do not draft a generic response that silently treats Major and Minor Revision as equivalent.
4. Select the decision-specific package strategy while preserving item-level severity.
5. Extract editor instructions first and assign IDs such as `E.1`, then split reviewer comments with IDs such as `R1.1`, `R1.2`, and `R2.1`.
6. Classify each item by category, severity, action label, work status, required input, expected output, finalization-blocking state, package readiness, and risk.
7. Create a response strategy summary before drafting prose.
8. Draft responses using preserved reviewer comments unless the mode is `triage-only`, `cover-letter`, or `appeal-like`.
9. For `cover-letter` or `revision-package`, draft a concise editor-facing cover letter that summarizes revision scope and points to the point-by-point response without duplicating it.
10. Map each claimed change to manuscript location, figure, table, supplement, citation, or explicit placeholder.
11. If editing manuscript text, create or instruct use of a backed-up manuscript copy and mark changed text in red. For LaTeX, use `\revised{...}` from `templates/revised-manuscript-redline.tex`.
12. If pasting revised manuscript text after a response, format it in italics. For LaTeX response files, use `\RevisedExcerpt{...}` from `templates/response-to-reviewers.tex`.
13. In LaTeX or print-oriented response letters, start each new reviewer response on a new page. Use `\ReviewerSection{1}`, `\ReviewerSection{2}`, etc. from `templates/response-to-reviewers.tex`.
14. If the user requests LaTeX, use `templates/cover-letter.tex`, `templates/response-to-reviewers.tex`, and/or `templates/revised-manuscript-redline.tex`; preserve visible placeholders for missing facts.
15. Mark a claimed change `VERIFIED_DONE` only after matching it to supplied revised manuscript text, analysis output, figure/table content, or another inspectable artifact. Treat an unsupported author report as `REPORTED_DONE_UNVERIFIED`.
16. Flag missing author input rather than fabricating details.
17. Run QA for completeness, decision-strategy consistency, per-item status calibration, blocking-state consistency, traceability, factuality, tone, unresolved risk, red-marked changes, italic revised excerpts, reviewer page breaks, and LaTeX placeholder visibility.
18. Derive package readiness from the item statuses and return one of: `ready_to_submit`, `draft_with_placeholders`, `needs_author_input`, or `blocked`.

## Output format

Unless the user asks for another format, return:

```text
Response strategy summary
- Decision type:
- Task mode:
- Overall posture:
- Major risks:
- Parsed email metadata:
- Suggested ordering:
- Package readiness:

Comment-response tracker
| ID | Reviewer concern | Type | Severity | Proposed action | Work status | Required input | Expected output | Blocks finalization? |
|---|---|---|---|---|---|---|---|---|

Draft point-by-point response letter
[editor-readable English response]

Draft revision cover letter
[only when requested or when returning a revision package]

Marked manuscript changes
- [red-marked changed passages or path to marked backup copy]

LaTeX files
- cover letter: [path or template-filled text when requested]
- response to reviewers: [path or template-filled text when requested]
- red-marked manuscript: [path or template-filled text when requested]

Manuscript change checklist
- [specific manuscript changes or placeholders]

Missing information / risk flags
- [specific unresolved items or "None"]

中文核对
- [when the user writes in Chinese; otherwise omit unless useful]
```
