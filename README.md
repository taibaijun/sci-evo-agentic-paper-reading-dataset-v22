# Sci-Evo Agentic Paper-Reading Dataset V22

This is the primary submission package for the Sci-Evo track.

## Primary Files

- `dataset.jsonl`: primary high-confidence Sci-Evo dataset, 142 cases.
- `samples_10.json`: 10 complete examples for quick review.
- `quality_report.json`: aggregate statistics and audit results.
- `docs/technical_report.md`: full technical report.
- `docs/data_card.md`: data card, scope, license, risks, and intended use.
- `docs/schema.md`: field definitions and JSONL contract.
- `docs/construction_pipeline.md`: reproducible construction workflow.
- `docs/mineru_usage.md`: how MinerU was used.
- `audits/`: deterministic evidence, structure, and rule audit outputs.
- `raw_data_samples/`: MinerU raw-output samples for 10 papers.
- `traces/`: replay artifacts for all 142 primary cases, including cases, events, and agent states.
- `code/`: code snapshot for generation, validation, and audits.
- `extended_candidate/`: non-primary 178-case candidate set kept only for transparency; do not use as the main submission file.

## Submission Identity

- Track/type: Sci-Evo, scientific evolution data.
- Domain: protein engineering and AI/computation-assisted biomolecular design.
- Main count: 142 cases.
- Average trajectory length: 11.43 steps.
- Evidence count: 4434 exact full-paper evidence quotes.

## Final Audit Summary

- Evidence audit: 0 bad evidence out of 4434 evidence spans.
- Structure audit: 142 pass, 0 repair, 0 issues.
- Rule audit: 142 pass, 0 review, 0 fail, 0 errors, 0 high warnings.
- Duplicate case IDs: 0.

## Recommended Submission

Use `dataset.jsonl` as the official dataset file. The extended 178-case candidate is included only to show the conservative filtering process; it is not the recommended main submission.

## Open Source Repository

Intended GitHub account/email: `taibaijun918@gmail.com`.

Recommended repository name: `sci-evo-agentic-paper-reading-dataset-v22`.

After the repository is created, use this URL in the competition submission form:

`https://github.com/taibaijun/sci-evo-agentic-paper-reading-dataset-v22`

## Internet Dataset Link

The competition form asks for an internet-accessible open dataset link. After uploading this package to a public repository or object store, fill the final link in `docs/submission_form_template.md`.
