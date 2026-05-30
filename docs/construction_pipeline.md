# Construction Pipeline

## Inputs

- Open-access scientific PDFs.
- MinerU parsed outputs under `docs/####/`.
- `combined.md` as the canonical final evidence source.

## Agentic Generation

The main generator is `code/scripts/sci_evo_agentic_generate.py`; supporting code is in `code/sci_evo_pipeline/`.

DeepSeek-v4-pro is used for paper-reading and trajectory construction. The model is not trusted as a final validator. Code performs the final checks.

## Per-Paper Flow

1. Plan reading from title, headings, abstract, and section structure.
2. Read key sections and build section memory.
3. Extract paper-native events chunk by chunk.
4. Build an event graph connecting events by follows/enables/refines/contradicts/validates relations.
5. Draft the Sci-Evo trajectory from the event graph.
6. Align evidence quotes to exact MinerU text.
7. Run self-critic for missing mainline, weak evidence, ordering, and hallucinated metrics.
8. Revise once with evidence constraints.
9. Run deterministic gates.
10. Keep only final rule-pass cases for submission.

## Deterministic Gates

- Schema validity.
- Evidence exactness against `combined.md`.
- Step count and per-step evidence coverage.
- Critical number/entity/mutation grounding.
- Source document consistency.
- Evidence reuse and phase-order sanity.

## Final Selection

The broad V22 generation produced a 178-case final candidate. For competition submission, the main dataset keeps only 142 cases with rule-audit `pass` and excludes 36 review-risk cases plus 2 hard fail cases. This prioritizes precision and scientific reliability over raw volume.

## Reproduction Commands

```powershell
python scripts\sci_evo_quality_evidence_audit.py --dataset-jsonl outputs\submission_v22_agentic_scievo_final\dataset.jsonl --mineru-root D:\mineru_flat_results_20260521_200done --output-json outputs\submission_v22_agentic_scievo_finaludits\quality_evidence_audit.json --output-csv outputs\submission_v22_agentic_scievo_finaludits\quality_evidence_audit.csv
python scripts\sci_evo_quality_structure_audit.py --dataset-jsonl outputs\submission_v22_agentic_scievo_final\dataset.jsonl --output-json outputs\submission_v22_agentic_scievo_finaludits\quality_structure_audit.json --output-csv outputs\submission_v22_agentic_scievo_finaludits\quality_structure_audit.csv
python scripts\sci_evo_rule_audit.py --dataset-jsonl outputs\submission_v22_agentic_scievo_final\dataset.jsonl --mineru-root D:\mineru_flat_results_20260521_200done --output-root outputs\submission_v22_agentic_scievo_finaluditsule_audit
```

API credentials are read from environment variables during generation and are not stored in this package.
