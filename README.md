# Sci-Evo 科学演化轨迹数据集 V22

Sci-Evo 科学演化轨迹数据集 V22 是一个面向 AI4Science 的开放数据集。数据集将开放获取的蛋白工程论文解析为可追溯的多步科研过程，覆盖研究问题、假设、设计选择、实验与分析、失败或部分结果、修订过程、验证方法和结论。

数据集的核心目标是让模型学习科学研究如何逐步推进，而不是只学习论文的最终结论。

## 数据概览

- 数据类型：Sci-Evo 科学演化轨迹数据。
- 研究领域：蛋白工程与 AI/计算辅助生物分子设计。
- 数据规模：142 条高置信样本。
- 轨迹步骤：1623 步，平均每条样本 11.43 步。
- 证据引用：4434 条全文证据。
- 完整样例：`samples_10.json`，包含 10 条完整数据样例。

## 数据来源

本数据集来源于开放获取科学论文。每条样本都保留源论文标题、DOI、许可信息、原始文件名、MinerU Markdown 路径和 `combined.md` 证据路径。

最终证据均来自 MinerU 解析后的全文文本，不使用无授权闭源数据，不生成或伪造实验结果。

## 文件结构

- `dataset.jsonl`：主数据集，每行一条完整 Sci-Evo 样本。
- `samples_10.json`：10 条完整样例。
- `quality_report.json`：数据统计和质量审计摘要。
- `docs/technical_report.md`：技术报告。
- `docs/data_card.md`：数据卡，说明范围、来源、许可、风险和适用场景。
- `docs/schema.md`：字段定义和 JSONL 结构约定。
- `docs/construction_pipeline.md`：数据构建流程。
- `docs/mineru_usage.md`：MinerU 在数据构建中的使用方式。
- `docs/license_and_ethics.md`：许可与伦理说明。
- `audits/`：证据、结构和规则审计输出。
- `raw_data_samples/`：10 篇论文的 MinerU 原始解析样例。
- `traces/`：样本构建过程的可追溯记录。
- `code/`：生成、验证和审计代码快照。

## 快速使用

```python
import json

with open("dataset.jsonl", "r", encoding="utf-8") as f:
    for line in f:
        item = json.loads(line)
        print(item["case_id"], len(item["evolution_trajectory"]))
```

每条样本均包含来源元数据、初始研究问题、演化轨迹、验证信息和质量控制信息。字段定义见 `docs/schema.md`。

## 质量审计

- 证据审计：4434 条证据片段中 0 条错误。
- 结构审计：142 条通过，0 条需修复，0 个结构问题。
- 规则审计：142 条通过，0 条需复核，0 条未通过，0 个高风险警告。
- 重复数据 ID：0。

详细结果见 `quality_report.json` 和 `audits/`。

## 许可

结构化标注层按 CC BY 4.0 发布。原论文文本、图表和证据引用仍受各自来源论文许可约束。使用者应根据每条样本的 `source.license`、`source.doi` 和相关来源字段确认二次使用范围。

## 引用

使用本数据集时，请引用本数据集以及样本对应的原始论文。引用信息见 `CITATION.cff`。
