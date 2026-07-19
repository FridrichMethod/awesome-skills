# `nature-response` Skill

[中文说明](README.md)

`nature-response` drafts, audits, and revises revision correspondence, including point-by-point reviewer responses, revision cover letters, red-marked manuscript excerpts, and editable LaTeX templates.

## What To Use It For

- Parse editor decision letters, revision emails, and reviewer reports.
- Split comments into stable IDs such as `E.1`, `R1.1`, and `R2.3`.
- Build response strategy, manuscript-change actions, and evidence needs for each comment.
- Track response action, task progress, and package readiness separately, with inspectable evidence for completed work.
- Draft formal, restrained, submission-ready English point-by-point responses and cover letters.
- Audit rebuttal drafts for missed replies, defensive tone, unsupported claims, and missing line numbers.

## Typical Requests

- "Here is the editor email and reviewer comments; generate a point-by-point response framework."
- "Turn my Chinese revision notes into English reviewer responses."
- "Check whether this rebuttal misses anything, sounds too strong, or lacks evidence."

## What You Need To Provide

- Editor decision letter, reviewer comments, revision requirements, or existing rebuttal draft.
- Completed or planned experiments, analyses, figures, line numbers, and manuscript-change locations.
- Target journal, manuscript ID, title, and required submission files.

## Outputs

- Response strategy summary.
- Point-by-point response letter, revision cover letter, or LaTeX response package.
- Manuscript-change checklist, missing-information checklist, and risk notes.
- Per-item tracker with work status, required input, expected output, and finalization-blocking state.
- Optional red-marked manuscript excerpts; manuscript text must come from the author.

## Boundaries

- The skill does not invent experiments, analyses, line numbers, figures, statistical results, or editor requirements.
- Information that needs author confirmation is marked in Chinese rather than written as fact.
- For pre-submission simulated review, use `nature-reviewer`.

## Related Skills

- `nature-reviewer`: simulate reviewer comments before submission.
- `nature-polishing`: polish reviewer-response and cover-letter English.
- `nature-statistics`: handle statistical reviewer comments.
- `nature-ref-verifier`: verify reference-error comments.
