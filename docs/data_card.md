# Data Card

## Dataset Name

Sci-Evo Agentic Paper-Reading Dataset V22.

## Type

Sci-Evo scientific evolution data.

## Version

High-confidence primary submission, generated 2026-05-30 from the V22 agentic pipeline.

## Size

- Main dataset: 142 cases.
- Extended candidate appendix: 178 cases.
- Main evidence spans: 4434.
- Total trajectory steps: 1623.

## Domain

Protein engineering and AI/computation-assisted biomolecular design.

## Source Data

Open-access scientific papers parsed by MinerU. Each case preserves DOI/license/source paths. Raw MinerU examples for 10 papers are included.

## Intended Uses

- Train or evaluate AI systems on scientific process understanding.
- Build retrieval systems over research trajectories.
- Study decision chains in protein engineering and biomolecular design.
- Evaluate evidence-grounded scientific agents.

## Out-of-Scope Uses

- Treating generated trajectories as executable lab protocols.
- Claiming new scientific results beyond what the source papers report.
- Removing source attribution or ignoring original source licenses.

## Annotation and Evidence Policy

Each step must cite at least one evidence quote. Final evidence is aligned against MinerU `combined.md`; unsupported or quote-mismatched cases are filtered out.

## Quality Results

- Evidence quote errors: 0.
- Structure issues: 0.
- Rule audit fail: 0.
- Rule audit review: 0.
- High warnings: 0.

## License Notes

The structured annotation layer can be released under CC BY 4.0 or a similar permissive license. Source paper text and quotes remain under each paper's original license. Per-case license metadata is retained in the `source.license` field.

## Repository

`https://github.com/taibaijun/sci-evo-agentic-paper-reading-dataset-v22`
