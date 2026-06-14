# 数据构建流程

## 输入

- 开放获取科学论文 PDF。
- MinerU 解析输出目录，形如 `docs/####/`。
- `combined.md`，作为最终证据引用对齐的标准全文来源。

## 智能体式生成

主生成入口是 `code/scripts/sci_evo_agentic_generate.py`，支撑模块位于 `code/sci_evo_pipeline/`。

DeepSeek-v4-pro 用于论文阅读、事件抽取和轨迹草拟。模型不作为最终裁判，最终质量由确定性代码检查。

## 单篇论文流程

1. 根据标题、章节、摘要和结构规划阅读重点。
2. 阅读关键章节，构建章节级记忆。
3. 从文本块中抽取论文原生科研事件。
4. 构建事件图，连接 follows、enables、refines、contradicts、validates 等关系。
5. 从事件图草拟 Sci-Evo 科研演化轨迹。
6. 将证据引用对齐到 MinerU 精确文本。
7. 运行 self-critic，检查主线缺失、弱证据、顺序问题和指标幻觉。
8. 在证据约束下进行一次修订。
9. 运行确定性质量门。
10. 只保留最终规则审计通过的样本。

## 确定性质量门

- 结构规范有效性。
- 证据与 `combined.md` 的精确匹配。
- 步骤数和每步证据覆盖。
- 关键数字、实体、突变信息证据支撑。
- 来源文档一致性。
- 证据复用和阶段顺序合理性检查。

## 复现命令

```powershell
python code\scripts\sci_evo_quality_evidence_audit.py --dataset-jsonl dataset.jsonl --mineru-root <MINERU_ROOT> --output-json audits\quality_evidence_audit.json --output-csv audits\quality_evidence_audit.csv
python code\scripts\sci_evo_quality_structure_audit.py --dataset-jsonl dataset.jsonl --output-json audits\quality_structure_audit.json --output-csv audits\quality_structure_audit.csv
python code\scripts\sci_evo_rule_audit.py --dataset-jsonl dataset.jsonl --mineru-root <MINERU_ROOT> --output-root audits\rule_audit
```

生成阶段从环境变量读取 API 凭证。本仓库不保存任何密钥。
