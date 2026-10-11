# Deep Reading Protocol

What a completed close reading of one paper contains. Load this when the reading is the main deliverable rather than a quick answer about one section.

## Reading order

The printed order is a teaching order, not the order the work happened in. Read the body, then the appendix, then return to the introduction with the results already known, so the framing can be compared against what was actually demonstrated.

Read figures and tables as evidence, not illustration. For each one, state what the authors want a reader to believe from it, then look for the details inside it that do not support that reading.

Record disagreements as you go. Body text reporting a different configuration, dataset size, or metric than the appendix is a finding, not a transcription error to smooth over.

## Worked micro-example standard

A formula is understood when it can be evaluated by hand on a small instance without returning to the paper.

- Give each symbol its shape, its units or meaning, and where it comes from.
- State what the formula is for before stating the formula.
- Follow key formulas with a micro-example using concrete numbers small enough to compute in a few lines, and carry it to the end. "Substituting gives" is not a worked example.
- Prefer one example that exposes the whole mechanism over several that restate the definition.
- When a formula reduces to a familiar case, say which case, and show the reduction.

## Load-bearing judgment

For each distinctive component, choose one position and name the evidence that supports it:

- **Load-bearing** — removing it collapses the reported result; supported by an ablation, a controlled comparison, or an appendix result.
- **Contributing** — removing it measurably weakens the result without collapsing it.
- **Decoration** — the result survives without it, or the paper never isolates it.

When the paper runs no control that isolates a component, the position is "not established", and that is the answer to report. Do not infer load-bearing status from how prominently a component is presented.

## Reconstruction checklist

- What was the state of the art before this work, and what specifically broke?
- Which claim is the paper's headline, and which result carries it?
- What did the authors give up to get the headline result — generality, cost, a simplifying assumption?
- Which choices are presented as arbitrary but are actually forced by the setup?
- What would falsify the central claim, and did the authors run that test?
- If the main result were an artifact of one hyperparameter, where would it show up?

## Deliverable shape

1. What the paper actually claims, in one paragraph, without the paper's own promotional framing.
2. The reconstructed path: the failure, the bet, the evidence for the bet.
3. The load-bearing judgment, component by component, with the evidence cited.
4. Worked micro-examples for the key formulas.
5. The evidence boundary — what the results do and do not establish.
6. What a reader should carry away, and which questions remain open.

## Failure modes

- Restating the abstract in longer words.
- Restating the introduction's narrative as if it were the authors' actual reasoning.
- Describing a formula symbol by symbol without ever evaluating it.
- Treating the contribution list as a summary of what the paper proved.
- Reporting a result without the condition it was obtained under.
- Filling a gap in the paper with a plausible assumption instead of naming the gap.
