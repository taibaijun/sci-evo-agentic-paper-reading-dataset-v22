# MinerU 使用说明

MinerU 在本项目中承担论文解析和文档理解底座的角色。

## 解析输出

对每篇论文，MinerU 会生成类似 `docs/0001/` 的目录，包含：

- `mineru.md`：MinerU 抽取出的 Markdown 文本。
- `combined.md`：规范化后的全文文本，也是最终证据对齐的标准来源。
- `content_list.json`：结构化内容块。
- `middle.json`：中间解析表示。
- `images/`：解析出的图表和页面图片资源。
- `status.json`：解析状态和元数据。

## 在数据集构建中的用途

V22 流程不会把 PDF 文件名或模型记忆当作最终证据。最终证据必须来自 `combined.md`。

MinerU 主要用于：

1. 抽取摘要、结果、方法、讨论、图表说明等论文内容；
2. 将长论文切分为适合事件抽取的文本块；
3. 对每条 证据引用 做全文匹配和可追溯校验；
4. 通过 `docs/####/combined.md` 路径保留来源文档链路。

## 随包原始样例

`raw_data_samples/docs/` 中包含 10 个完整 MinerU 样例目录，包含 `combined.md`、`mineru.md`、`content_list.json` 和 `status.json` 等文件。它们展示了原始数据格式，同时避免在仓库中分发全部源论文解析结果。
