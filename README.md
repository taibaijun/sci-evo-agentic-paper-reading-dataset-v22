# Sci-Evo 科学演化轨迹数据集 V22

这是本项目的正式提交包，面向 **Sci-Evo 科学演化轨迹数据集** 赛道。数据集把开放获取的蛋白工程论文，通过 MinerU 解析、智能体式论文阅读和确定性质量审计，整理成可追溯、可解析、证据对齐的多步科研过程数据。

## 评审快速入口

- 赛道类型：**Sci-Evo**，科学演化轨迹数据集。
- 主数据文件：`dataset.jsonl`，共 142 条高置信 样本。
- 完整样例：`samples_10.json`，包含 10 条完整数据样例。
- 技术报告：`docs/technical_report.md`。
- 字段说明：`docs/schema.md`。
- 构建流程：`docs/construction_pipeline.md`。
- MinerU 使用说明：`docs/mineru_usage.md`。
- 原始数据样例：`raw_data_samples/docs/`，包含 10 篇 MinerU 解析输出。
- 质量审计：`audits/` 与 `quality_report.json`。
- 构建代码：`code/`，包含生成、校验和审计脚本。
- 公开数据集链接：`https://github.com/taibaijun/sci-evo-agentic-paper-reading-dataset-v22`。

## 主要文件

- `dataset.jsonl`：正式主数据集，142 条高置信 Sci-Evo 数据。
- `samples_10.json`：10 条完整样例，便于快速审阅。
- `quality_report.json`：整体统计和审计摘要。
- `docs/technical_report.md`：完整技术报告。
- `docs/data_card.md`：数据卡，说明范围、许可、风险和适用场景。
- `docs/schema.md`：字段定义和 JSONL 结构约定。
- `docs/construction_pipeline.md`：可复现的数据构建流程。
- `docs/mineru_usage.md`：MinerU 在构建过程中的使用方式。
- `audits/`：证据、结构和规则审计输出。
- `raw_data_samples/`：10 篇论文的 MinerU 原始解析样例。
- `traces/`：142 条主数据的可追溯过程记录，包括 样本、事件 和 智能体状态。
- `code/`：数据生成、验证和审计代码快照。
- `extended_candidate/`：178 条扩展候选集，仅用于展示筛选过程，不作为正式主提交。

## 提交身份

- 数据类型：Sci-Evo，科学演化数据。
- 研究领域：蛋白工程与 AI/计算辅助生物分子设计。
- 主数据规模：142 条 样本。
- 平均轨迹长度：11.43 步。
- 证据引用数量：4434 条全文精确证据。

## 质量审计摘要

- 证据审计：4434 条 证据片段 中 0 条错误。
- 结构审计：142 条通过，0 条需修复，0 个结构问题。
- 规则审计：142 条通过，0 条 需复核，0 条 未通过，0 个 错误，0 个 高风险警告。
- 重复数据 ID：0。

## 推荐提交方式

正式数据集文件使用 `dataset.jsonl`。`extended_candidate/` 中的 178 条候选集仅用于说明我们采用了保守筛选策略，不建议作为主数据提交。

## 开源仓库与数据集链接

公开仓库：

`https://github.com/taibaijun/sci-evo-agentic-paper-reading-dataset-v22`

提交表中“互联网可访问数据集链接”建议填写同一个公开仓库地址。
