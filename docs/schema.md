# 字段结构说明

`dataset.jsonl` 是 UTF-8 JSON Lines 文件。每一行是一条完整 样本。

## 根字段

- `case_id` string：稳定标识符，例如 `sci_evo_0004`。
- `dataset_type` string：固定为 `Sci-Evo`。
- `domain` string：科学领域标签。
- `source` object：论文元数据和 MinerU 路径。
- `initial_request` object：研究问题和初始背景。
- `evolution_trajectory` array：有顺序的科研决策与观察过程。
- `success_verification` object：验证方法、指标、结论和局限。
- `quality_control` object：可追溯信息和质量控制元数据。

## `source`

- `title`：论文标题。
- `doi`：DOI 或 DOI URL。
- `url`：来源 URL。
- `license`：来源许可信息。
- `raw_file`：原始 PDF 文件名。
- `mineru_md`：MinerU Markdown 路径。
- `combined_md`：规范化全文证据路径。

## `initial_request`

- `research_problem`：论文要解决的科学问题。
- `target_object`：蛋白、酶、通路、分子或系统。
- `known_context`：轨迹开始前已有背景。
- `constraints`：实验或设计约束列表。
- `input_data`：可用输入数据列表。
- `quantifiable_goals`：可量化目标列表。

## `evolution_trajectory[]`

每个步骤要求包含：

- `step_index`：整数，从 1 开始顺序递增。
- `phase`：取值为 `hypothesis`、`design`、`simulation`、`experiment`、`analysis`、`revision`、`validation`。
- `state_before`：进入本步骤前的状态。
- `gap_or_uncertainty`：尚未解决的问题。
- `hypothesis`：本步骤对应的局部科学假设。
- `decision`：选择的决策或行动。
- `action_type`：取值为 `literature_reasoning`、`dry_experiment`、`wet_experiment`、`analysis`。
- `tool_or_method`：包含 `name`、`version`、`category` 的方法或工具对象。
- `parameters`：键值形式参数。
- `observation`：本步骤后的结果或观察。
- `result_status`：取值为 `success`、`failure`、`partial`、`inconclusive`。
- `next_step_reason`：为什么自然进入下一步。
- `evidence`：精确证据引用或证据片段列表。

## `evidence[]`

- `evidence_id`：样本内稳定证据 ID。
- `source_file`：应指向 `docs/####/combined.md`。
- `section`：章节或 chunk 标签。
- `quote_or_span`：来自 MinerU 全文文本的精确或规范化精确 引用。

## 验证约定

数据集样本必须满足：

- 每一行都能解析为合法 JSON。
- 所有必需根字段存在。
- 最终高置信集合的步骤数在 7 到 12 之间。
- 每个步骤都有证据。
- 证据引用 能在对应来源文档中解析匹配。
- 关键数字、突变、实体 token 有证据支撑。
- 规则审计结果为 `通过`。
