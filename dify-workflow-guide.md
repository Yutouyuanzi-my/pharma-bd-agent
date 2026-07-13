# Dify 工作流模板：竞品监测 Agent

> 适用于 Dify Cloud（dify.ai）网页版，与 Python Agent 的逻辑一致。
> 可作为 Python 工程实现之外的低代码对照方案，复用同一套数据源与工具逻辑。

## 工作流结构

```
[开始]
  ↓
[变量赋值] ← condition, sponsor（可选）, since_days
  ↓
[路由判断] ← 用户输入是什么类型？
  ├─ "监测" → 每日/每周监测流程
  │   ├─ [HTTP 节点] ← 搜索过去 N 天新增/更新的试验
  │   └─ [LLM 节点] ← 生成监测简报
  ├─ "格局" → 竞争格局分析流程
  │   ├─ [HTTP 节点] ← 搜索全部相关试验
  │   ├─ [代码节点] ← 按申办方、阶段分组
  │   └─ [LLM 节点] ← 生成格局分析报告
  └─ "对比" → 试验对比流程
      ├─ [HTTP 节点] ← 获取每个 NCT ID 的详情
      └─ [LLM 节点] ← 侧边对比分析
  ↓
[结束]
```

## HTTP 节点配置

### 基础搜索

```
方法: GET
URL: https://clinicaltrials.gov/api/v2/studies?query.term={{condition}}&pageSize=20&format=json
```

### 按申办方搜索（关键 BD 功能）

```
方法: GET
URL: https://clinicaltrials.gov/api/v2/studies?query.adv=AREA[Condition]:"{{condition}}" AND AREA[Sponsor]:"{{sponsor}}"&pageSize=20&format=json
```

### 监测最近更新（每日/每周简报核心）

```
方法: GET
URL: https://clinicaltrials.gov/api/v2/studies?query.adv=AREA[Condition]:"{{condition}}" AND AREA[LastUpdatePostDate]RANGE[{{since_date}},MAX]&pageSize=50&format=json&sort=LastUpdatePostDate
```

> ⚠️ 如果 cloud IP 被 ban，所有 URL 的 `clinicaltrials.gov` 换成本地隧道地址。

## LLM 节点 Prompt

### 监测简报 Prompt

```
你是一名药企 BD 分析师。以下是过去 {{since_days}} 天內 {{condition}} 领域
新增或更新的临床试验。

{{trial_data}}

请生成一份中文 BD 晨报，包含：
1. 本周亮点（最重要的 2-3 个变化）
2. 主要药企动态
3. 阶段分布变化
4. 值得关注的趋势
```

### 格局分析 Prompt

```
分析 {{condition}} 领域的竞争格局。

主要玩家：
{{sponsor_data}}

阶段分布：
{{phase_data}}

请生成中文分析报告：
1. 领域概览（总试验数、活跃数）
2. 主要药企管线分析
3. 各阶段竞争密度
4. BD 策略建议
```

## Python Agent vs Dify Workflow

| 对比 | Python Agent | Dify Workflow |
|---|---|---|
| 工具调度 | LLM auto function calling | 手动路由 + 条件判断 |
| 灵活性 | Agent 自主决策调用链 | 固定流水线 |
| 竞品监测 | `monitor_recent_changes` 查新+更新 | 两个 HTTP 节点分别查 |
| 格局分析 | `analyze_competitive_landscape` 自动分组 | 代码节点手动分组 |
| 调试性 | 代码断点 | Dify 日志面板 |
| 能力体现 | 展现底层 Agent 机制的实现能力 | 展现低代码快速搭建的能力 |

## 导入方式

1. Dify 工作室 → 新建空白应用（Workflow 类型）
2. 按上述结构拖拽节点
3. 填写 URL 和 Prompt
4. 建议用「聊天流」类型，保持对话上下文
5. 发布后可通过 API 或嵌入使用
