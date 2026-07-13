# 项目：药企 BD 竞品监测 Agent

## 项目简介
- 场景：药企 BD 自动监测 ClinicalTrials.gov 竞争对手临床试验动态，输出竞争格局、近期动态、竞品对比与 AI 简报。

## 技术架构
- 主力实现：纯 Python + OpenAI Function Calling（无 Agent 框架），文件 agent.py
- 前端：Streamlit 三栏 Dashboard（浅灰白+暖橙莫兰迪风格），app.py
- 数据源：ClinicalTrials.gov API v2 + PubMed E-utilities（官方API，非爬虫）
- 多模型：通过 .env 的 DEEPSEEK_BASE_URL/DEEPSEEK_MODEL 兼容任意 OpenAI 协议端点，默认 deepseek-chat
- 6个核心工具：search_clinical_trials / get_trial_detail / search_pubmed / analyze_competitive_landscape / monitor_recent_changes / compare_trials_side_by_side
- 后续新增：中国药企管线/CDE审批工具、Plotly可视化、请求缓存重试、NCT超链接、风险标签

## 项目约定
- 代码注释用中文；PRD 有中英双语（PRD.md 英文 / PRD.zh-CN.md 中文）
- Dify 只有指南文档 dify-workflow-guide.md，未实际搭建
- 已推送到 GitHub（public）：https://github.com/Yutouyuanzi-my/pharma-bd-agent

## 安全约定
- **严禁在任何文件（代码 / 记忆 / 文档 / 提交）中写入真实密钥或其片段**，仅用变量名（如 `DEEPSEEK_API_KEY`）指代。
- 2026-07-13 发生过密钥泄露事故（.env.example 含真实 DeepSeek key，且曾写入 MEMORY.md），已删除 .env.example、改用 run.sh 内置模板生成 .env，并清理全部 git 历史（filter-branch + gc）。
- 建议去 DeepSeek 控制台**重置该 key** 以彻底作废；仓库现已公开，但密钥从未出现在任何提交中（历史已清理）。

## 重要提醒
- 2026-07-13：发现 .env.example 曾硬编码真实 DeepSeek API Key 且被 git 追踪。已改为占位符、删除该文件并清理全部 git 历史；建议去 DeepSeek 控制台重置该 key 以彻底作废。仓库已公开，密钥从未出现在任何提交中。
