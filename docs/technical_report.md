# Technical Report: Sci-Evo Agentic Paper-Reading Dataset V22

## 1. Dataset Overview

This dataset targets the Sci-Evo track. Each record turns an open-access scientific paper into a machine-readable research trajectory: initial problem, evolving hypotheses, design choices, dry/wet experiments, observations, failures or partial results, revisions, validation, and final scientific conclusion.

The primary submission contains 142 high-confidence cases selected from a larger 178-case candidate pool. The submitted set is intentionally conservative: only cases that passed the deterministic rule audit are included in `dataset.jsonl`.

## 2. Scientific Motivation

The goal is to help AI systems reason about how scientific work develops over time, not only memorize final facts. Protein engineering papers are well suited for this because they commonly include:

- explicit design goals and constraints;
- multi-round computational and experimental decisions;
- negative or partial results that redirect the research path;
- measurable endpoints such as activity, yield, stability, affinity, expression, enrichment, or fold improvement;
- tool-rich workflows involving mutagenesis, screening, sequencing, structure modeling, machine learning, and biochemical validation.

## 3. Data Structure

Each JSONL row contains one Sci-Evo case. The main fields are:

- `case_id`: stable ID, `sci_evo_####`.
- `dataset_type`: always `Sci-Evo`.
- `domain`: currently `protein_engineering`.
- `source`: title, DOI, license, MinerU paths, and source PDF metadata.
- `initial_request`: research problem, target object, context, input data, constraints, and goals.
- `evolution_trajectory`: ordered 7-12 step scientific process.
- `success_verification`: validation methods, metrics, conclusion, and limitations.
- `quality_control`: traceability and automated quality notes.

Each trajectory step includes phase, state before the step, uncertainty, hypothesis, decision, action type, method/tool, parameters, observation, result status, next-step reason, and evidence quotes.

## 4. Construction Method

The V22 pipeline is an agentic paper-reading workflow powered by DeepSeek-v4-pro and deterministic guardrails.

1. `plan_reading`: plan which sections are relevant from title, headings, and structure.
2. `read_sections`: build section-level memory from abstract, results, methods, discussion, figures, and tables.
3. `extract_events`: extract paper-native scientific events from chunks without seeing candidate answers.
4. `build_event_graph`: merge events and infer relations such as follows, enables, refines, contradicts, and validates.
5. `draft_trajectory`: draft a 5-12 step Sci-Evo trajectory from the event graph.
6. `quote_align`: deterministically align every evidence quote to `combined.md`.
7. `self_critic`: ask the model to check missing mainline, ordering, weak evidence, and hallucinated metrics.
8. `revise_once`: perform one constrained revision using only the evidence bank and critic feedback.
9. `deterministic_gate`: enforce schema, step count, quote exactness, critical entity/number grounding, and source consistency.
10. `final_filter`: keep only rule-audit pass cases for the primary submission.

The AI proposes structure and scientific interpretation; code owns evidence exactness, schema validity, source traceability, filtering, and packaging.

## 5. MinerU Usage

PDFs were parsed with MinerU into per-document outputs including `mineru.md`, `content_list.json`, `middle.json`, images, and status files. The pipeline uses `combined.md` as the sole evidence source for final quote alignment. A quote must appear in the corresponding MinerU text for the case to pass.

Raw MinerU examples for 10 papers are included in `raw_data_samples/docs/`.

## 6. Statistics

- Primary cases: 142.
- Total steps: 1623.
- Steps per case: min 7, max 12, average 11.43.
- Total evidence quotes: 4434.
- Average evidence quotes per case: 31.23.
- Result statuses: `{"success": 1311, "partial": 190, "failure": 71, "inconclusive": 51}`.
- Action types: `{"wet_experiment": 628, "analysis": 605, "dry_experiment": 210, "literature_reasoning": 180}`.
- Phases: `{"experiment": 489, "analysis": 424, "design": 223, "validation": 199, "hypothesis": 159, "revision": 72, "simulation": 57}`.

## 7. Quality Evaluation

Three deterministic audits were rerun on the final primary dataset:

- Evidence audit: 0 bad evidence out of 4434 evidence spans.
- Structure audit: 142 pass, 0 repair, 0 issues.
- Rule audit: 142 pass, 0 review, 0 fail, 0 errors, 0 high warnings.
- Duplicate case IDs: 0.

The 178-case extended candidate contained 36 review-risk cases and 2 rule-fail cases. They were excluded from the primary dataset to maximize reliability.

## 8. Compliance and Ethics

The dataset is derived from open-access scientific papers. Source title, DOI, license, and MinerU paths are preserved per record. The dataset does not fabricate experiments: every trajectory step must cite evidence from the parsed full paper. Users should respect the original paper licenses; annotation files may be released under a permissive license, but source text remains governed by source licenses.

## 9. Usage

`dataset.jsonl` can be loaded line by line. Each line is independent and contains the complete source metadata, trajectory, and evidence needed for training, evaluation, or agent memory construction.

The dataset is suitable for:

- scientific reasoning and research-process modeling;
- agent decision-trace training;
- evidence-grounded trajectory retrieval;
- evaluation of multi-step scientific planning and revision.

It is not intended as a laboratory protocol database or as a replacement for reading the original papers.
