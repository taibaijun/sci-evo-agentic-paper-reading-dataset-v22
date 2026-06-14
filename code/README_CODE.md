# 代码快照说明

本目录包含 V22 数据生成与质量验证所使用的本地代码快照。

- `scripts/sci_evo_agentic_generate.py`：基于 DeepSeek-v4-pro 的智能体式生成入口。
- `scripts/sci_evo_quality_evidence_audit.py`：证据引用 对齐审计。
- `scripts/sci_evo_quality_structure_audit.py`：结构和文本卫生审计。
- `scripts/sci_evo_rule_audit.py`：确定性规则审计。
- `sci_evo_pipeline/`：共享 结构规范、模型客户端和智能体流程模块。

生成阶段从环境变量读取 API 凭证。本仓库不包含任何 API key。
