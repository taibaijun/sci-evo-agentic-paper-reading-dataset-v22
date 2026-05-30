# Sci-Evo Competition Pipeline

This is the formal local pipeline for building a Sci-Evo dataset from the MinerU-parsed paper corpus.

## Stages

1. Rank papers by Sci-Evo signal strength.
2. Retrieve compact evidence snippets from MinerU Markdown.
3. Use DeepSeek JSON mode to extract one structured Sci-Evo case per paper.
4. Normalize and validate schema fields.
5. Produce `dataset.jsonl`, `samples_10.json`, quality reports, and a draft submission package.

## DeepSeek

The API key is read only from `DEEPSEEK_API_KEY`.

Recommended first run:

```powershell
$env:DEEPSEEK_API_KEY="..."
python scripts\sci_evo_build_index.py
python scripts\sci_evo_extract_cases.py --limit 3 --output-root outputs\deepseek_trial
python scripts\sci_evo_validate_dataset.py --cases-dir outputs\deepseek_trial\cases --output-jsonl outputs\deepseek_trial\dataset.jsonl --report outputs\deepseek_trial\quality_report.json
python scripts\sci_evo_make_pack.py --run-root outputs\deepseek_trial --pack-dir outputs\submission_draft
```

For full run after confirmation:

```powershell
python scripts\sci_evo_extract_cases.py --limit 200 --output-root outputs\deepseek_full
```

## Important Review Rules

- Do not treat generated content as final until evidence quotes and metrics are checked.
- Use `unknown` instead of filling missing scientific details.
- Keep original DOI/license/MinerU paths for traceability.
- Prefer high-quality cases over sheer volume for the final submission.

