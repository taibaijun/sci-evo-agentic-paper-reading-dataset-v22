# Code Snapshot

This directory contains the local code used for V22 generation and validation.

- `scripts/sci_evo_agentic_generate.py`: agentic DeepSeek-v4-pro generation entry point.
- `scripts/sci_evo_quality_evidence_audit.py`: evidence quote audit.
- `scripts/sci_evo_quality_structure_audit.py`: structure/text hygiene audit.
- `scripts/sci_evo_rule_audit.py`: deterministic rule audit.
- `sci_evo_pipeline/`: shared schema, client, and agentic pipeline modules.

Generation reads API credentials from environment variables. No API key is stored in this package.
