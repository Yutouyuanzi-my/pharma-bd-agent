# 产品需求文档：药企 BD 竞品监测 Agent

## 1. 问题描述

**问题**：药企商务拓展（BD）专业人员每天上午需要花费 2-3 小时手动检查 ClinicalTrials.gov 上的竞争对手更新：新注册试验、状态变更、阶段转换。当前工作流程是手动的、容易出错的，并且无法跨多个治疗领域扩展。

**目标用户**：
- 主要用户：药企 BD / 企业战略分析师
- 次要用户：生物科技和药企公司的竞争情报团队
- 第三用户：追踪治疗领域动态的 VC 投资者

## 2. 用户故事

| 优先级 | 用户故事 |
|---|---|
| P0 | 作为 BD 分析师，我希望看到过去一周我关注的治疗领域中的所有新试验 |
| P0 | 作为 BD 分析师，我想知道每个竞争对手在特定适应症中正在做什么 |
| P1 | 作为 BD 分析师，我想要一个格局概览：哪些申办方、哪些阶段、有多少试验 |
| P1 | 作为 BD 分析师，我想并排对比竞争对手的试验 |
| P2 | 作为 BD 分析师，我希望自动接收每日邮件/Slack 简报 |
| P3 | 作为 BD 总监，我想同时追踪多个治疗领域 |

## 3. 功能需求

### Agent MVP（最小可行产品）
- F1：按疾病条件、申办方/公司、状态搜索试验
- F2：竞争格局分析（申办方分组、阶段分布、LLM 总结）
- F3：近期变更监测（每日/每周新增和更新试验）
- F4：并排试验对比
- F5：多语言输出（中文为主，英文为辅）

### V1 增强功能
- F6：通过邮件 / Slack webhook 自动发送每日简报
- F7：保存监测列表（疾病条件 + 申办方组合）
- F8：添加欧盟临床试验注册库（EU Clinical Trials Register）和中国临床试验注册中心（ChiCTR）数据源

## 4. 成功指标

| 指标 | 目标 |
|---|---|
| 每位分析师每天节省的时间 | 2+ 小时 |
| 试验漏检率 | < 5% |
| 预警延迟（试验发布 → 用户收到通知） | < 24 小时 |
| 用户留存率（周活跃） | > 80% |

## 5. 技术架构

```
[Streamlit UI] → [Agent 控制器 (OpenAI 函数调用)] → [工具层]
                                                    ├─ ClinicalTrials.gov API (v2)
                                                    ├─ PubMed E-utilities API
                                                    └─ LLM 分析 (gpt-4o-mini)
```

关键设计决策：纯 OpenAI 函数调用（无 Agent 框架）、中文优先输出、异步就绪的工具层。

## 6. 竞争格局

| 产品 | 优势 | 劣势 |
|---|---|---|
| Cortellis (Clarivate) | 全面，包含交易数据 | 昂贵（每年 $10k+），数据封闭 |
| GlobalData | 适合药企 | 无实时试验监测 |
| ClinicalTrials.gov 原生 | 免费、权威 | 无个性化、无监测功能 |
| **我们的产品** | 免费 + AI 驱动、专注 BD、支持中文 | MVP 阶段、仅限美国数据 |

## 7. 风险与缓解措施

| 风险 | 缓解措施 |
|---|---|
| ClinicalTrials.gov API 限流 | 缓存、错开查询 |
| WAF 阻止云服务器 IP | 本地中继 / 住宅代理 |
| 竞争分析时 LLM 产生幻觉 | 先使用结构化数据，LLM 仅作为总结工具 |
| 数据源仅限于美国 | 路线图包括欧盟 + 中国注册库 |

## 8. 下一步计划

1. ✅ MVP：具备 6 个工具的 BD 情报 Agent
2. ⬜ 与 3 位药企 BD 专业人员进行用户测试
3. ⬜ 自动每日简报推送（cron + 邮件）
4. ⬜ 多数据源：整合 EUCTR + ChiCTR
5. ⬜ Dify 工作流并行构建（用于产品经理验证）

---

# Product Requirements Document: Pharma BD Competitive Intelligence Agent

## 1. Problem Statement

**Problem**: Pharma Business Development professionals spend 2-3 hours every morning manually checking ClinicalTrials.gov for competitor updates: new registrations, status changes, phase transitions. Current workflow is manual, error-prone, and doesn't scale across multiple therapeutic areas.

**Target users**:
- Primary: Pharma BD / Corporate Strategy analysts
- Secondary: Competitive Intelligence teams at biotech and pharma companies
- Tertiary: VC investors tracking therapeutic area activity

## 2. User Stories

| Priority | Story |
|---|---|
| P0 | As a BD analyst, I want to see all new trials in my therapeutic area from the past week |
| P0 | As a BD analyst, I want to know what each competitor is doing in a specific indication |
| P1 | As a BD analyst, I want a landscape overview: which sponsors, phases, and how many trials |
| P1 | As a BD analyst, I want to compare competitor trials side-by-side |
| P2 | As a BD analyst, I want to receive daily email/Slack briefings automatically |
| P3 | As a BD director, I want to track multiple therapeutic areas simultaneously |

## 3. Functional Requirements

### Agent MVP
- F1: Search trials by condition, sponsor/company, and status
- F2: Competitive landscape analysis (sponsor grouping, phase distribution, LLM summary)
- F3: Recent change monitoring (daily/weekly new & updated trials)
- F4: Side-by-side trial comparison
- F5: Multi-language output (Chinese primary, English secondary)

### V1 Enhancements
- F6: Automated daily briefing via email / Slack webhook
- F7: Saved watchlists (condition + sponsor combinations)
- F8: Add EU Clinical Trials Register and ChiCTR data sources

## 4. Success Metrics

| Metric | Target |
|---|---|
| Time savings per analyst/day | 2+ hours |
| Missed trial detection rate | < 5% |
| Alert latency (trial posted → user notified) | < 24 hours |
| User retention (weekly active) | > 80% |

## 5. Technical Architecture

```
[Streamlit UI] → [Agent Controller (OpenAI FC)] → [Tool Layer]
                                                    ├─ ClinicalTrials.gov API (v2)
                                                    ├─ PubMed E-utilities API
                                                    └─ LLM Analysis (gpt-4o-mini)
```

Key design decisions: pure OpenAI function calling (no agent framework), Chinese-first output, async-ready tool layer.

## 6. Competitive Landscape

| Product | Strengths | Weaknesses |
|---|---|---|
| Cortellis (Clarivate) | Comprehensive, includes deals data | Expensive ($10k+/yr), closed data |
| GlobalData | Good for pharma | No real-time trial monitoring |
| ClinicalTrials.gov native | Free, authoritative | No personalization, no monitoring |
| **Ours** | Free + AI-powered, BD-focused, Chinese support | MVP stage, US data only |

## 7. Risk & Mitigation

| Risk | Mitigation |
|---|---|
| ClinicalTrials.gov API throttling | Caching, staggered queries |
| WAF blocks cloud IPs | Local relay / residential proxy |
| LLM hallucination on competitive analysis | Structured data first, LLM as summarizer only |
| Data source limited to US | Roadmap includes EU + China registries |

## 8. Next Steps

1. ✅ MVP: Agent with 6 tools for BD intelligence
2. ⬜ User testing with 3 pharma BD professionals
3. ⬜ Automated daily briefing delivery (cron + email)
4. ⬜ Multi-source: EUCTR + ChiCTR integration
5. ⬜ Dify workflow parallel build (for PM validation)
