# `nature-statistics` 技能

`nature-statistics` 用于审查、改写或起草 Nature / 高影响力期刊投稿中的统计报告文本。它关注的是论文中统计信息是否足够透明、可复核、与实验设计一致，而不是把所有统计问题简化成“p 值是否显著”。

该技能适合处理中文作者常见的投稿场景：作者可以用中文描述样本量、重复数、统计检验、图注或审稿意见；技能会把这些信息整理成保守的英文 Statistical analysis、Results 统计表述或图注统计说明，并标记仍需作者确认的事实。

## 功能

- 审查 Statistical analysis / Methods 中的统计报告是否完整。
- 检查 Results 里 p 值、置信区间、效应量、样本量和检验名称是否表述清楚。
- 区分 biological replicates、technical replicates、重复测量、细胞/视野/子样本和独立实验单位。
- 识别伪重复、嵌套数据、未校正多重比较、错误的交互解释、过度依赖显著性、相关性过度解释等常见问题。
- 改写图注中的统计说明，包括 error bars、box plots、violin plots、stars、exact p values、source data 和 n 定义。
- 根据审稿人统计意见，生成逐点修改建议或可粘贴的保守回应文本。
- 在信息缺失时输出 `AUTHOR_INPUT_NEEDED`，不替作者编造统计细节。

## 适用场景

- 投稿前检查 Statistical analysis 小节。
- 审稿人指出 “statistical analysis is unclear / insufficient”。
- 图中星号、误差线、n 数和检验方法需要统一说明。
- 需要把中文统计描述改成英文稿件可用文本。
- 需要判断某个结果是否存在伪重复、多重比较或模型假设问题。
- 需要让 Results 中的统计语言更克制，避免把显著性写成机制或因果。

## 默认返回内容

常规审查会返回：

1. `Statistics review scope`
2. `Major statistical issues`
3. `Ready-to-paste revision`
4. `AUTHOR_INPUT_NEEDED`
5. `Reviewer-risk note`

如果用户只是要求起草统计方法，技能会返回更短的：

1. `Draft Statistical analysis`
2. `Reporting notes`

## 核心规则

- 先确认实验设计和独立分析单位，再讨论统计检验。
- 不把细胞、图像、技术重复、重复读数或模拟次数默认当作独立样本。
- 优先报告效应量、置信区间、样本量、检验方法和校正策略，而不是只报告星号。
- 不编造 p 值、自由度、样本量、软件版本、排除标准、随机化、盲法或 power analysis。
- 当材料不足时，给出保守文本和短问题清单，而不是替作者补事实。
- 统计结果不能自动证明机制、因果或生物学重要性。

## 文件结构

```text
nature-statistics/
├── README.md
├── README_EN.md
├── SKILL.md
├── manifest.yaml
└── references/
    ├── source-basis.md
    ├── statistical-reporting.md
    ├── common-failure-modes.md
    ├── figure-statistics.md
    └── reviewer-checklist.md
```

## 状态

Draft。第一版聚焦统计报告与审稿风险检查，尚未用真实匿名稿件库做系统回归测试。
