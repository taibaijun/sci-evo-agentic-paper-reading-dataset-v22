# Schema

`dataset.jsonl` is UTF-8 JSON Lines. Each line is one complete case object.

## Root Fields

- `case_id` string: stable identifier, e.g. `sci_evo_0004`.
- `dataset_type` string: always `Sci-Evo`.
- `domain` string: scientific domain label.
- `source` object: paper metadata and MinerU paths.
- `initial_request` object: research problem and starting context.
- `evolution_trajectory` array: ordered scientific decisions and observations.
- `success_verification` object: validation methods, metrics, conclusion, limitations.
- `quality_control` object: traceability and quality metadata.

## `source`

- `title`: paper title.
- `doi`: DOI or DOI URL when available.
- `url`: source URL when available.
- `license`: source license text from metadata.
- `raw_file`: original PDF filename.
- `mineru_md`: MinerU Markdown path.
- `combined_md`: canonical evidence text path.

## `initial_request`

- `research_problem`: scientific problem being addressed.
- `target_object`: protein, enzyme, pathway, molecule, or system.
- `known_context`: background known before the trajectory.
- `constraints`: list of experimental/design constraints.
- `input_data`: list of available inputs.
- `quantifiable_goals`: list of measurable goals.

## `evolution_trajectory[]`

Required fields per step:

- `step_index`: integer, sequential from 1.
- `phase`: one of `hypothesis`, `design`, `simulation`, `experiment`, `analysis`, `revision`, `validation`.
- `state_before`: state before this decision.
- `gap_or_uncertainty`: unresolved question.
- `hypothesis`: local scientific hypothesis.
- `decision`: decision/action selected.
- `action_type`: one of `literature_reasoning`, `dry_experiment`, `wet_experiment`, `analysis`.
- `tool_or_method`: object with `name`, `version`, `category`.
- `parameters`: key-value object.
- `observation`: result or observation after the step.
- `result_status`: one of `success`, `failure`, `partial`, `inconclusive`.
- `next_step_reason`: why the next step follows.
- `evidence`: list of exact quotes or spans.

## `evidence[]`

- `evidence_id`: stable local evidence ID.
- `source_file`: expected to point to `docs/####/combined.md`.
- `section`: section/chunk label.
- `quote_or_span`: exact or normalized-exact quote from the MinerU full text.

## Validation Contract

A primary case is included only if:

- JSON parses as one line.
- All required root fields exist.
- Step count is between 7 and 12 for the final high-confidence set.
- Every step has evidence.
- Evidence quotes resolve to the source document.
- Critical number/mutation/entity tokens are grounded.
- Rule audit decision is `pass`.
