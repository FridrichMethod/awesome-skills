# Evidence Boundary

Where a paper's evidence stops, and how to report that honestly. Load this when the reading must establish what the results do and do not support.

## Number agreement

- Do the body text, tables, and figures report the same value at the same precision?
- Is every performance number attached to the condition it was obtained under — dataset split, model size, number of runs?
- Are error type and sample size stated, or is a bare mean reported?
- When a figure and a table disagree, both are findings; report the disagreement rather than picking one.

## Baseline alignment

An improvement is only an improvement if the comparison is fair.

- Same training data, same step budget, same tuning effort?
- Was the baseline reproduced by the authors, or copied from a paper that used a different setup?
- Is the baseline's reported number its best configuration or a default one?
- If the baseline's own paper needed a warmup, schedule, or trick, was that applied here?

An under-tuned baseline does not establish an improvement, and a missing baseline budget statement is a gap, not a pass.

## Selection pressure

- Were hyperparameters, checkpoints, or prompts chosen on the test set, or with test-set knowledge?
- Is the reported result the best of several runs, with the others unmentioned?
- Was the evaluation metric chosen after seeing which one favors the method?
- If a threshold or stopping rule was tuned, on what data was it tuned?

## Leakage

- Does any preprocessing step see test data, directly or through fitted statistics such as normalization constants, vocabulary, or cluster centers?
- Are duplicates between train and test possible — near-duplicate documents, overlapping subjects, re-uploaded images?
- For pretrained components, could the evaluation set have been in the pretraining corpus?
- Is the split random, or does it respect the grouping that the scientific question requires?

## Cost and scope

- Compute, memory, latency, and the deployment shape the method assumes.
- Whether the claim holds at the scale the paper ran at, versus the scale the claim implies.
- The stated limitations, and whether the results actually support them or merely concede them.
- Which subpopulation, domain, or regime the evidence covers, and where the conclusion stops applying.

## Reporting gaps

Preserve the source's modality. "May" is not "does"; "suggests" is not "shows"; "some settings" is not "all settings"; an unreported result is not evidence of no effect.

Where the paper does not report something the conclusion needs, write that the paper does not report it. Do not substitute a plausible number, an assumed default, or a value remembered from a similar paper. Mark any judgment that goes beyond the supplied material as your inference, and keep inference visibly separate from what the source states.

## Severity

Rank what you find, and keep the ranking grounded in the paper's own claim:

- **Changes the conclusion** — the headline claim does not survive.
- **Weakens the conclusion** — the direction holds but the magnitude or the generality does not.
- **Limits the scope** — true as stated, narrower than a reader would assume.
- **Presentation only** — the evidence is fine; the reporting is unclear.

Report severity as a reading observation. Acceptance decisions, scores, and novelty judgments belong to `nature-reviewer`.
