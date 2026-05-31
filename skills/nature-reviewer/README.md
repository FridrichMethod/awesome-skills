# `nature-reviewer` skill

A reviewer-assessment skill for simulating a `Nature`-style referee package from the reviewer perspective rather than the author-rebuttal perspective.

This skill was created specifically from the reviewer-related content in `Nature`'s official `Editorial criteria and processes` page:
`https://www-nature-com/nature/for-authors/editorial-criteria-and-processes`

The motivation is narrow and explicit:

- extract the reviewer-relevant rules from that official `Nature` source
- ensure the simulated reviewer behaviour stays consistent with those rules
- avoid drifting into generic peer-review habits or invented reviewer personas
- produce a reusable `nature-reviewer` skill that reflects the official source basis as closely as possible within the repository's skill format

Accordingly, this skill is intentionally conservative. It is grounded in the local copy of that source under `references/editorial criteria and processes.md`, then converted into a conservative output contract: `3 reviewer reports + 1 cross-review synthesis`. The three reports differ only by `emphasis`, because the source supports reviewer function and report content, but does not define fictional reviewer identities or specialty personas.

## What it does

- reads a manuscript draft, abstract, selected sections, figures, or author notes as a reviewer-facing input package
- evaluates the work against source-grounded `Nature`-style axes: `originality`, `scientific importance`, `interdisciplinary readership`, `technical soundness`, and `readability for nonspecialists`
- generates `3` reviewer reports that differ only in `emphasis`, not in invented identity or specialty
- states who would be interested in the results and why
- identifies technical failings that must be addressed before the authors' case is established
- synthesizes consensus and emphasis differences across the three reports
- flags unsupported claims and material that cannot be assessed from the supplied evidence

## When to use

- simulating a `Nature` reviewer report before submission
- stress-testing whether a manuscript makes a credible broad-interest case
- asking for a reviewer-style assessment of novelty, significance, or technical soundness
- generating a pre-submission critique from the referee perspective
- evaluating whether a manuscript is readable to non-specialists
- obtaining a bounded peer-review style response without drafting an author rebuttal

If the user wants a point-by-point author response or revision letter, use `nature-response` instead.

## What it returns

Unless the user asks for another format, the skill returns:

1. `Review setup`
2. `Reviewer 1`
3. `Reviewer 2`
4. `Reviewer 3`
5. `Cross-review synthesis`
6. `Risk / unsupported claims`

## Core rules

- Ground the assessment in the local reviewer source and the user-supplied manuscript facts only.
- Keep the three reviewers aligned on the same facts; vary only the weighting of those facts.
- Do not invent reviewer identities, narrow specialty roles, institutions, or hidden knowledge.
- Explicitly address `who will be interested in the new results and why`.
- Explicitly identify `technical failings` that still block the authors' case.
- Distinguish technical validity from broad-interest fit; the source treats these as related but not identical.
- Mark `AUTHOR_INPUT_NEEDED`, `Not assessable from provided material`, or equivalent uncertainty labels instead of fabricating details.

## Source hierarchy

- `references/editorial criteria and processes.md` as the primary authoritative local source
- user-supplied manuscript facts and evidence
- conservative local implementation rules summarized in `references/source-basis.md`

This skill must not silently expand beyond that source basis into generic reviewer-role invention or journal-policy speculation.

## File structure

```text
nature-reviewer/
├── README.md
├── SKILL.md
└── references/
    ├── editorial criteria and processes.md
    ├── source-basis.md
    ├── reviewer-workflow.md
    ├── review-axes.md
    ├── report-structure.md
    ├── role-boundaries.md
    └── qa-checklist.md
```

## Status

Draft. The first version is source-defined and structured for grounded reviewer simulation, but it has not yet been validated against a library of real anonymized manuscript-review examples.
