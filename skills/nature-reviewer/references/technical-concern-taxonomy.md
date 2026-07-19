# Technical concern taxonomy

Use this reference to build an internal concern ledger after the five source-grounded Nature axes have been assessed. It is a coverage and traceability aid, not an official journal taxonomy, reviewer-persona selector, or historical-frequency model.

## Twelve internal axes

| Axis | Check only when applicable |
|---|---|
| `novelty-significance` | The claimed advance is distinguished from prior work and its importance is supported rather than asserted. |
| `mechanism-evidence` | Mechanistic statements are supported by discriminating evidence rather than a compatible observation alone. |
| `experimental-design` | Comparators, controls, replication units, conditions, sampling, and bias controls support the stated inference. |
| `statistical-rigor` | Estimands, assumptions, uncertainty, multiplicity, power, and model validation are adequate for the claim. |
| `reproducibility` | Methods, code, data, versions, seeds, protocols, and reporting detail permit independent scrutiny or reuse where appropriate. |
| `clinical-validity` | Cohort definition, endpoint choice, external validation, calibration, clinical utility, and generalizability support clinical claims. |
| `ethical-governance` | Human/animal approvals, consent, privacy, dual-use, permissions, and responsible data handling are reported when required. |
| `data-resource-quality` | Dataset completeness, provenance, documentation, quality control, accessibility, and intended reuse are credible. |
| `figures-and-tables` | Visual encodings, labels, denominators, uncertainty, scale bars, legends, and accessibility accurately represent the results. |
| `writing-clarity` | The argument, terminology, abstract/body consistency, and nonspecialist explanation make the evidence chain understandable. |
| `claim-moderation` | Strength, scope, novelty, generality, and translational language do not exceed the supplied evidence. |
| `causal-vs-correlative` | Association, prediction, mediation, intervention, and causation are distinguished according to study design and evidence. |

## Applicability rule

For every axis, record one of:

- `applicable`: the manuscript makes a claim or presents evidence that activates the check;
- `not applicable`: the axis is genuinely outside the manuscript's design or claims;
- `not assessable`: the axis could matter, but the supplied material is insufficient.

Do not turn `not assessable` into a presumed flaw. State the assessment boundary when the missing material affects confidence.

## Concern construction

Emit a concern only when it is supported by the supplied manuscript material. Record:

- `issue_key`: a concise normalized key used to detect overlap;
- `axis`: one primary technical axis;
- `severity`: `major` or `minor` according to effect on the authors' case;
- `claim_pointer`: a faithful paraphrase of the challenged claim or affected reporting element;
- `evidence_pointer`: a verified section, figure, table, page, or line location;
- `evidence_status`: `located`, `location_missing`, or `not_assessable`;
- `concern`: why the visible evidence does not yet support the claim or reporting need;
- `resolution_test`: what evidence, analysis, clarification, or claim adjustment would close the concern.

Use `location not provided` when the critique is grounded but the exact location cannot be verified. Never manufacture a location to make the ledger look complete.

## Reviewer allocation

- Keep the visible roles as `Reviewer 1`, `Reviewer 2`, and `Reviewer 3` with allowed emphasis labels.
- Allocate applicable axes across the three reports to improve coverage, but ensure every emitted concern remains relevant to that report's emphasis.
- Do not expose specialist personas such as `Statistics Reviewer` or infer reviewer-selection history.
- Reuse the same `issue_key` when more than one reviewer independently raises the same underlying issue; this enables honest consensus and overlap checks.
