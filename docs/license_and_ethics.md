# License and Ethics Notes

## Source Licensing

This submission is built from open-access scientific papers. Each case keeps source metadata in `source.title`, `source.doi`, `source.license`, `source.raw_file`, `source.mineru_md`, and `source.combined_md`.

The structured annotation layer is intended for open research use. Original paper text, figures, and quoted evidence remain governed by the corresponding source paper licenses. Users should check the per-case `source.license` field before redistributing source text.

## No Fabricated Scientific Results

The dataset does not claim new experiments. It structures and summarizes research trajectories reported by source papers. Every trajectory step has evidence quotes aligned against MinerU full text, and final primary cases passed quote, schema, source, and critical-token grounding audits.

## Sensitive and Safety Considerations

The dataset is designed for scientific reasoning and AI4Science workflow research. It is not an executable wet-lab protocol collection. Users should not use it to bypass laboratory safety review, biosafety review, or domain expert validation.

## Attribution

When using the dataset, cite both this dataset package and the original papers represented in each case.
