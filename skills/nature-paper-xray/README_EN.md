# `nature-paper-xray` Skill

[中文说明](README.md)

`nature-paper-xray` reads one supplied paper closely enough to retell the authors' reasoning: where they got stuck, what they bet on, which design carries the result, what each formula looks like on concrete numbers, and how far the evidence actually reaches. It is not a summary, not a translation, and not a peer review.

## What To Use It For

- Understand a paper well enough to present it at a group meeting, journal club, or defense.
- Work out what a paper actually did and what gap it left, before building on it.
- Get to grips with the formulas in a methods paper, including the shape and meaning of every symbol and a hand-computable example.
- Read a paper with impressive-looking results and see its control conditions, ablations, and scope before deciding how much to trust it.
- Prepare for reviewing or writing related work by pinning down the mechanism and the evidence boundary first.

## Typical Requests

- "Read this paper closely for me — I want to know how the authors actually arrived at this design."
- "What does each term in this formula mean? Give me an example I can work through myself."
- "What does the first figure want me to believe, and does it hold up?"
- "Is the baseline comparison fair? Were hyperparameters picked on the test set?"
- "Which design choices carry the result, and which ones could be removed without changing the conclusion?"

## What You Need To Provide

- The paper itself: a PDF, an arXiv identifier or link, a publisher HTML page, or pasted text.
- The appendix and supplementary material if you have them — appendices carry the ablations and real search ranges the body leaves out.
- Your purpose: understanding it, writing related work, reviewing it, or presenting it. This sets the depth.
- Optional: the paper's official code repository. Code exposes normalization, warmup, and data filtering the paper never mentions, and the performance sometimes comes from exactly there.

## Outputs

One Markdown long-read, in this order:

1. What the paper actually claims, without its own promotional framing.
2. The reconstructed research path: the failure, the bet, the evidence for the bet.
3. The load-bearing judgment, component by component, with the evidence that supports it.
4. Worked micro-examples for the key formulas.
5. The evidence boundary: what the results do and do not establish.
6. What a reader should carry away, and which questions remain open.

## Boundaries

- **It reads, it does not judge.** It reports what the paper does and how far its evidence reaches. It does not score, rank, or assess acceptance readiness, novelty, or significance — that is `nature-reviewer`.
- It does not extract reusable writing patterns or prose templates.
- It does not translate papers or produce a bilingual reading edition.
- It does not search the literature, verify citations, or supply references on the paper's behalf.
- It does not draft manuscript prose. Hand the reading to `nature-writing` when positioning or writing related work.
- Where the paper does not report something, it says so. It never substitutes a plausible number.

## Related Skills

| Skill | Division of labor |
|------|------|
| `nature-reviewer` | Produces the reviewer verdict, graded comments, and scores; this skill only supplies the input |
| `nature-reader` | Full translation and bilingual reading editions; this skill does not translate |
| `nature-writing` | Drafts and restructures manuscript sections; this skill does not write prose |
| `nature-academic-search` | Searches for related work and literature; this skill does not go looking |
| `nature-ref-verifier` | Checks whether citations exist and whether their metadata is correct |
