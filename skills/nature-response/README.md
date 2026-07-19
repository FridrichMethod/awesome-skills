# `nature-response` 技能

[English](README_EN.md)

`nature-response` 用于起草、审查和修改返修通信材料，包括逐点 reviewer response、revision cover letter、标红修改稿摘录和可编辑 LaTeX 模板。

## 适合用它做什么

- 解析编辑部决定信、返修邮件和 reviewer reports。
- 将意见拆成稳定编号，例如 `E.1`、`R1.1`、`R2.3`。
- 为每条意见制定回应策略、手稿修改动作和证据需求。
- 分开记录“采用什么回应动作”“任务做到哪一步”“整个回复包能否提交”，并要求完成状态有可核验材料。
- 起草正式、克制、可提交的英文逐点回复和 cover letter。
- 审查 rebuttal 草稿中的遗漏回复、防御性语气、无支撑声称和行号缺口。

## 典型请求

- “这是编辑邮件和审稿意见，帮我生成逐点回复框架。”
- “把我的中文修改说明改成英文 reviewer response。”
- “检查这份 rebuttal 是否漏回、语气是否太强、有没有缺证据。”

## 你需要提供

- 编辑决定信、审稿意见、返修要求或已有 rebuttal 草稿。
- 已完成或计划完成的实验、分析、图表、行号和手稿修改位置。
- 目标期刊、稿件号、题名和提交材料要求。

## 产出

- Response strategy summary。
- 逐点回复信、返修 cover letter 或 LaTeX response package。
- 手稿修改清单、缺失信息清单和风险提示。
- 带任务状态、所需输入、预期产物和是否阻塞最终提交的逐条 tracker。
- 可选标红修改稿摘录；原文修改必须基于作者提供的文本。

## 边界

- 不会编造实验、分析、行号、图版、统计结果或编辑要求。
- 对需要作者确认的信息会用中文标记，而不是直接写成事实。
- 如果任务是模拟投稿前审稿意见，优先使用 `nature-reviewer`。

## 相关技能

- `nature-reviewer`：投稿前模拟审稿人意见。
- `nature-polishing`：回复信和 cover letter 的英文语气打磨。
- `nature-statistics`：处理统计相关审稿意见。
- `nature-ref-verifier`：核查参考文献错误类意见。
