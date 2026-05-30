# Sci-Evo 比赛构建流程说明

这是基于 MinerU 解析论文语料构建 Sci-Evo 数据集的本地流程说明。

## 阶段

1. 建立论文索引。
2. 从 MinerU Markdown 中检索紧凑证据片段。
3. 使用 DeepSeek JSON mode，为每篇论文抽取一条结构化 Sci-Evo 样本。
4. 校验 JSONL 格式、必需字段和证据。
5. 生成最终提交包。

## DeepSeek

API key 只从 `DEEPSEEK_API_KEY` 环境变量读取。

推荐首次运行：

```powershell
python scripts\sci_evo_build_index.py --mineru-root D:\mineru_flat_results_20260521_200done --output outputs\sci_evo_index.jsonl
python scripts\sci_evo_extract_cases.py --index-jsonl outputs\sci_evo_index.jsonl --output-jsonl outputs\deepseek_trial\dataset.jsonl --limit 5
python scripts\sci_evo_validate_dataset.py --dataset-jsonl outputs\deepseek_trial\dataset.jsonl --output-report outputs\deepseek_trial\validation_report.json
python scripts\sci_evo_make_pack.py --dataset-jsonl outputs\deepseek_trial\dataset.jsonl --output-dir outputs\submission_draft
```

正式生成时可以去掉 `--limit`，或改成更大的数量。

## 重要审查规则

- 不得编造实验结果。
- 缺失的科学细节应填写 `unknown`，不能硬补。
- DOI、license 和 MinerU 路径必须保留，保证可追溯。
- 每个轨迹步骤都必须有证据支撑。
