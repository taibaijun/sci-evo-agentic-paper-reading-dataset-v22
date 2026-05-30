# Project Pitch Slides

---

## Sci-Evo Agentic Paper-Reading Dataset V22

Evidence-grounded scientific evolution trajectories from MinerU-parsed open-access protein-engineering papers.

---

## Problem

AI systems need data that teaches how science develops: uncertainty, hypothesis, method choice, failed attempts, revision, and validation. Plain QA or static summaries do not capture the decision process.

---

## Dataset

- 142 high-confidence Sci-Evo cases.
- 1,623 trajectory steps.
- 4,434 full-paper evidence quotes.
- 7-12 steps per paper.
- Every step links to source evidence.

---

## Architecture

DeepSeek-v4-pro proposes paper-reading plans, event extraction, event graphs, trajectories, critic feedback, and one constrained revision. Deterministic code owns quote alignment, schema validation, number/entity grounding, source consistency, and final filtering.

---

## Why It Is Agentic

The system first discovers paper-native events, builds relations between events, then derives the research trajectory. It is not a single prompt that asks for a final answer from a whole paper.

---

## Quality Strategy

A broader 178-case candidate pool was generated. The primary submission keeps only 142 rule-pass cases and excludes 36 review-risk plus 2 hard-fail cases.

---

## Audit Results

- Evidence audit: 0 bad spans / 4,434.
- Structure audit: 142 pass / 0 repair.
- Rule audit: 142 pass / 0 review / 0 fail.
- Duplicate case IDs: 0.

---

## MinerU Role

MinerU converts PDFs into Markdown and structured content. `combined.md` is the canonical evidence source. Final quotes must resolve to MinerU full text.

---

## Value

The dataset supports training and evaluation of scientific agents that need to reason over multi-step experimental and computational research workflows.

---

## Deliverables

`dataset.jsonl`, examples, technical report, data card, schema, construction pipeline, MinerU raw samples, audits, traces, and code snapshot.
