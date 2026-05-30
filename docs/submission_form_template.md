# Submission Form Template

Use this as a checklist when filling the official competition submission form.

## Dataset Link

TODO: upload `submission_v22_agentic_scievo_final.zip` to an internet-accessible public location and paste the URL here.

## Dataset Type

Sci-Evo.

## Dataset Name

Sci-Evo Agentic Paper-Reading Dataset V22.

## Short Description

A high-confidence evidence-grounded Sci-Evo dataset that converts open-access protein-engineering papers parsed by MinerU into multi-step scientific evolution trajectories. Each case records research problem, hypotheses, design choices, wet/dry experiments, failures or partial results, revisions, validation methods, metrics, and exact evidence quotes.

## Main Dataset File

`dataset.jsonl`, 142 cases.

## Original Data Samples

`raw_data_samples/docs/` contains 10 MinerU parsed-paper samples.

## Technical Report

`docs/technical_report.md`.

## Construction Code

`code/` contains the generation and audit code snapshot. Credentials are not included.

## Quality Summary

- Evidence audit: 0 bad evidence spans out of 4434.
- Structure audit: 142 pass, 0 repair, 0 issues.
- Rule audit: 142 pass, 0 review, 0 fail, 0 errors, 0 high warnings.

## Open Source Repository

Recommended repo: `https://github.com/<github-username>/sci-evo-agentic-paper-reading-dataset-v22`

Use account/email: `taibaijun918@gmail.com`.
