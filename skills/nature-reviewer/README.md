# `nature-reviewer` 技能

[English](README_EN.md)

`nature-reviewer` 用于从审稿人视角模拟 Nature 风格的预投稿评审，帮助作者在投稿前发现 novelty、significance、technical soundness 和读者价值上的风险。

## 适合用它做什么

- 对手稿、摘要、图表或结果故事线做投稿前压力测试。
- 按 Nature 官方审稿维度评估 originality、scientific importance、interdisciplinary readership、technical soundness 和 readability。
- 生成三份重点不同的 reviewer reports 和一份 cross-review synthesis。
- 标记无支撑声称、技术缺陷、证据链断点和非专业读者理解障碍。
- 用内部 12 轴技术清单检查覆盖范围，并为每条实质性意见绑定 claim pointer 和可核验的证据位置。
- 对三份报告做重复度检查；只有至少两位 reviewer 提出同一问题时才列为共识。
- 判断哪些读者会关心这项工作，以及为什么。

## 典型请求

- “像 Nature reviewer 一样审这篇 introduction 和 Figure 1。”
- “投稿前帮我找最可能被审稿人攻击的技术问题。”
- “给我三份 reviewer reports 和一个综合判断，不要写 rebuttal。”

## 你需要提供

- 手稿全文、摘要、关键章节、图表、图注或作者说明。
- 目标期刊、学科领域和你最担心的审稿风险。
- 已有补充实验或不能新增实验的限制。

## 产出

- 三份 peer-review style reports。
- Cross-review synthesis：共识问题、分歧重点和编辑层风险。
- 带稳定编号、claim pointer、evidence pointer 和解决判据的可追溯审稿意见。
- 必须补强的实验、分析、叙事或图表证据清单。
- 对无证据判断的明确标记。

## 边界

- 不会虚构具体审稿人身份、专业人设或编辑决定。
- 只基于用户提供材料和技能内官方审稿规则做保守模拟。
- 如果目标是写返修回复，优先使用 `nature-response`。

## 相关技能

- `nature-response`：把真实审稿意见转成回复包。
- `nature-writing`：根据评审风险重建手稿叙事。
- `nature-statistics`：深入审查统计设计和报告。
