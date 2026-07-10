"""
药企 BD 竞争情报 Agent 的 Streamlit 前端界面。

运行方式：streamlit run app.py

这个文件负责：
1. 注册所有可用工具（供 Agent 调用）
2. 渲染 Streamlit UI（输入框、筛选面板、图表、结果展示）
3. 处理用户交互（点击按钮、输入查询、调用 Agent）
"""

import os
import json
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from tools import (
    search_clinical_trials,
    get_trial_detail,
    search_pubmed,
    analyze_competitive_landscape,
    monitor_recent_changes,
    compare_trials_side_by_side,
    search_chinese_pipeline,
    search_cde_approvals,
)
from agent import register_tool, run_agent

# ── 工具注册 ──

register_tool("search_clinical_trials", search_clinical_trials, {
    "description": "Search ClinicalTrials.gov by condition, sponsor/company, and status.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Disease, condition, or keyword, e.g. 'NSCLC' or 'CAR-T'"},
            "sponsor": {"type": "string", "description": "Sponsor/company name, e.g. 'Roche', 'AstraZeneca'"},
            "status": {"type": "string", "description": "Trial status filter: RECRUITING, ACTIVE_NOT_RECRUITING, COMPLETED, etc."},
            "page_size": {"type": "integer", "description": "Number of results (max 20)", "default": 10},
        },
        "required": ["query"],
    },
})
register_tool("get_trial_detail", get_trial_detail, {
    "description": "Get full protocol details for a specific study by NCT ID.",
    "parameters": {
        "type": "object",
        "properties": {
            "nct_id": {"type": "string", "description": "NCT ID like 'NCT04267848'"},
        },
        "required": ["nct_id"],
    },
})
register_tool("analyze_competitive_landscape", analyze_competitive_landscape, {
    "description": "Analyze the competitive landscape for a therapeutic area. Groups trials by sponsor, phase, and produces a structured CI report.",
    "parameters": {
        "type": "object",
        "properties": {
            "condition": {"type": "string", "description": "Therapeutic area or condition, e.g. 'NSCLC', 'HER2+ breast cancer'"},
            "sponsor": {"type": "string", "description": "Optional: Focus on a specific sponsor/company"},
        },
        "required": ["condition"],
    },
})
register_tool("monitor_recent_changes", monitor_recent_changes, {
    "description": "Monitor recent changes: find new or updated trials in a therapeutic area. Core daily monitoring tool for BD.",
    "parameters": {
        "type": "object",
        "properties": {
            "condition": {"type": "string", "description": "Therapeutic area or condition to monitor"},
            "since_days": {"type": "integer", "description": "How many days back to check (default 7)", "default": 7},
        },
        "required": ["condition"],
    },
})
register_tool("compare_trials_side_by_side", compare_trials_side_by_side, {
    "description": "Compare up to 5 trials side by side: sponsor, phase, design, outcomes, competitive positioning.",
    "parameters": {
        "type": "object",
        "properties": {
            "nct_ids": {"type": "array", "items": {"type": "string"}, "description": "List of NCT IDs to compare"},
        },
        "required": ["nct_ids"],
    },
})
register_tool("search_pubmed", search_pubmed, {
    "description": "Search PubMed for scientific articles on a medical topic.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "PubMed search query"},
            "max_results": {"type": "integer", "description": "Maximum number of articles", "default": 5},
        },
        "required": ["query"],
    },
})
register_tool("search_chinese_pipeline", search_chinese_pipeline, {
    "description": "Search Chinese pharma company pipeline trials on ClinicalTrials.gov. Filters for Chinese sponsors like BeiGene, Hengrui, Innovent, etc.",
    "parameters": {
        "type": "object",
        "properties": {
            "condition": {"type": "string", "description": "Therapeutic area or condition, e.g. \"NSCLC\", \"PD-1\""},
            "sponsor": {"type": "string", "description": "Optional: specific Chinese pharma company name"},
            "page_size": {"type": "integer", "description": "Number of results", "default": 10},
        },
        "required": ["condition"],
    },
})
register_tool("search_cde_approvals", search_cde_approvals, {
    "description": "Query CDE (China Center for Drug Evaluation) drug approval pipeline. Provides links to CDE data platform and related Chinese trial info.",
    "parameters": {
        "type": "object",
        "properties": {
            "drug_name": {"type": "string", "description": "Drug name in Chinese or English, e.g. \"替雷利珠单抗\", \"tislelizumab\""},
            "milestone": {"type": "string", "description": "Optional: approval milestone filter"},
        },
        "required": ["drug_name"],
    },
})


# ── 页面配置 ──

st.set_page_config(page_title="Pharma BD Intelligence Agent", page_icon="🏢", layout="wide")
st.title("🏢 Pharma BD Competitive Intelligence Agent")
st.markdown(
    "Monitor competitor pipelines, analyze clinical trial landscapes, and get daily briefings — "
    "all powered by an AI agent that searches ClinicalTrials.gov and PubMed."
)


# ── 辅助渲染函数 ──

def _render_trial_table(studies: list[dict], title: str = "临床试验") -> str:
    """将试验列表渲染为 Markdown 表格（含原文链接和风险标签）。"""
    if not studies:
        return ""
    rows = ["| NCT ID | 标题 | 申办方 | 阶段 | 状态 | 标签 |", "|---|---|---|---|---|---|"]
    for s in studies[:10]:
        nct = s.get("nct_id", "")
        link = s.get("nct_link", f"https://clinicaltrials.gov/study/{nct}")
        title_text = s.get("brief_title", "")[:60]
        sponsor = s.get("sponsor", "")[:20]
        phase = s.get("phase", "") or "-"
        status = s.get("overall_status", "") or "-"
        tags = ", ".join(s.get("risk_tags", [])) or "-"
        rows.append(f"| [{nct}]({link}) | {title_text} | {sponsor} | {phase} | {status} | {tags} |")
    return "\n".join(rows)


def _render_pubmed_table(articles: list[dict]) -> str:
    """将文献列表渲染为 Markdown 表格。"""
    if not articles:
        return ""
    rows = ["| PMID | 标题 | 摘要 |", "|---|---|---|"]
    for a in articles[:5]:
        pmid = a.get("pmid", "")
        link = a.get("pubmed_link", f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/")
        title = a.get("title", "")[:60]
        abstract = a.get("abstract", "")[:100].replace("\n", " ")
        rows.append(f"| [{pmid}]({link}) | {title} | {abstract} |")
    return "\n".join(rows)


def _render_charts_from_trace(trace: list[dict]):
    """从工具调用轨迹中提取结构化数据，绘制图表。"""
    # 找 analyze_competitive_landscape 的结果
    for step in trace:
        if step.get("tool") == "analyze_competitive_landscape":
            try:
                raw = step.get("result_preview", "")
                # 尝试从 trace 的完整 result 中解析（trace 存的是截断版，这里靠 agent.py 塞入的完整数据）
                data = json.loads(step.get("_full_result", raw))
            except (json.JSONDecodeError, KeyError):
                continue

            top_sponsors = data.get("top_sponsors", [])
            phase_dist = data.get("phase_distribution", {})

            if top_sponsors:
                df_sponsor = {
                    "申办方": [s["sponsor"][:15] for s in top_sponsors],
                    "试验数": [s["trial_count"] for s in top_sponsors],
                }
                st.subheader("🏢 主要申办方试验分布")
                st.bar_chart(df_sponsor, x="申办方", y="试验数", use_container_width=True)

            if phase_dist:
                phases_with_counts = {p: len(v) for p, v in phase_dist.items() if v}
                if phases_with_counts:
                    st.subheader("📊 各阶段试验分布")
                    df_phase = {"阶段": list(phases_with_counts.keys()), "试验数": list(phases_with_counts.values())}
                    st.bar_chart(df_phase, x="阶段", y="试验数", use_container_width=True)

            break  # 只处理第一个 landscape 结果

    # 找 search_clinical_trials 的结果 → 渲染表格
    for step in trace:
        if step.get("tool") == "search_clinical_trials":
            try:
                raw = step.get("_full_result", step.get("result_preview", ""))
                data = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, KeyError):
                continue
            studies = data.get("studies", []) if isinstance(data, dict) else []
            if studies:
                st.subheader("📋 检索结果")
                st.markdown(_render_trial_table(studies))
            break

    # 找 monitor_recent_changes 的结果
    for step in trace:
        if step.get("tool") == "monitor_recent_changes":
            try:
                raw = step.get("_full_result", step.get("result_preview", ""))
                data = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, KeyError):
                continue
            studies = data.get("studies", []) if isinstance(data, dict) else []
            if studies:
                st.subheader(f"📅 近期更新 ({data.get('since_date', '')})")
                st.markdown(_render_trial_table(studies))
            break

    # 找 search_pubmed 的结果
    for step in trace:
        if step.get("tool") == "search_pubmed":
            try:
                raw = step.get("_full_result", step.get("result_preview", ""))
                data = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, KeyError):
                continue
            articles = data.get("articles", []) if isinstance(data, dict) else []
            if articles:
                st.subheader("📄 相关文献")
                st.markdown(_render_pubmed_table(articles))
            break


# ── 侧边栏：设置 + 筛选面板 ──

with st.sidebar:
    st.header("⚙️ Settings")

    api_key = st.text_input(
        "API Key", type="password",
        value=os.getenv("OPENAI_API_KEY", os.getenv("DEEPSEEK_API_KEY", "")),
        help="支持 OpenAI 及任何兼容 OpenAI 协议的端点（如 DeepSeek）。也可在 .env 中配置。",
    )

    model = st.selectbox(
        "Model",
        ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "deepseek-chat"],
        index=0,
    )
    custom_model = st.text_input("自定义模型名（可选）", value="", help="例如 deepseek-reasoner")
    if custom_model.strip():
        model = custom_model.strip()

    base_url = st.text_input(
        "API Base URL（可选）",
        value=os.getenv("OPENAI_BASE_URL", os.getenv("DEEPSEEK_BASE_URL", "")),
        help="DeepSeek 填 https://api.deepseek.com",
    )

    st.divider()
    st.header("🔍 筛选条件")

    # 结构化筛选控件
    filter_sponsor = st.text_input("申办方名称", value="", placeholder="如 AstraZeneca, Roche…")
    filter_status = st.selectbox(
        "试验状态", ["", "RECRUITING", "ACTIVE_NOT_RECRUITING", "COMPLETED",
                      "TERMINATED", "WITHDRAWN", "SUSPENDED", "ENROLLING_BY_INVITATION"],
        index=0,
    )
    filter_phase = st.multiselect(
        "临床分期", ["Phase 1", "Phase 2", "Phase 3", "Phase 4"],
        default=None,
    )
    filter_days = st.number_input("监测时间范围（天）", min_value=1, max_value=365, value=7)

    st.divider()
    st.markdown("### 💼 BD Use Cases")
    st.markdown(
        "**Competitive Landscape**\n"
        '- "Show me the competitive landscape for NSCLC"\n'
        '- "What is Roche doing in breast cancer?"\n\n'
        "**Daily Monitoring**\n"
        '- "What changed in the last week for CAR-T?"\n'
        '- "Any new GLP-1 trials this month?"\n\n'
        "**Deep Dive**\n"
        '- "Compare NCT04267848 and NCT04191356"\n'
        '- "What trials does AstraZeneca have for EGFR mutant NSCLC?"'
    )


# ── 快捷操作按钮 ──

st.markdown("### 快捷操作")
col_a, col_b, col_c, col_d = st.columns(4)
with col_a:
    if st.button("📊 NSCLC 竞争格局", use_container_width=True):
        st.session_state.preset_query = "分析 NSCLC 的竞争格局，列出主要药企的试验分布"
with col_b:
    if st.button("🔍 AstraZeneca 在做什么", use_container_width=True):
        st.session_state.preset_query = "AstraZeneca 在 NSCLC 领域有哪些临床试验？各处于什么阶段？"
with col_c:
    if st.button("📅 CAR-T 本周更新", use_container_width=True):
        st.session_state.preset_query = "过去一周 CAR-T 疗法有什么新的临床试验？请列出新增和更新的试验"
with col_d:
    if st.button("⚖️ 对比两个试验", use_container_width=True):
        st.session_state.preset_query = "帮我对比一下 NCT04267848 和 NCT04191356，从试验设计、入排标准和竞争定位角度分析"

# 初始化 session_state（首次加载）
if "preset_query" not in st.session_state:
    st.session_state.preset_query = ""

# ── 查询输入框 ──

query_placeholder = (
    "e.g.: 分析一下 NSCLC 领域的竞争格局，重点关注 PD-1/PD-L1 药物的临床试验分布。\n"
    "或者：帮我看一下这周有哪些新的 CAR-T 临床试验登记了。"
)

query = st.text_area(
    "输入你的查询",
    value=st.session_state.get("preset_query", ""),
    placeholder=query_placeholder,
    height=100,
)

# 用户手动修改了输入后，清除预设值（避免覆盖用户手写内容）
if query != st.session_state.get("preset_query", ""):
    st.session_state.preset_query = ""

col1, col2 = st.columns([1, 5])
with col1:
    run_btn = st.button("▶ Run Agent", type="primary", use_container_width=True)


# ── 主要运行逻辑 ──

if run_btn:
    if not api_key:
        st.error("请先在侧边栏填入 API Key。")
        st.stop()
    if not query.strip():
        st.error("请输入查询内容。")
        st.stop()

    # ── 构建包含筛选条件的查询 ──
    filter_parts = []
    if filter_sponsor.strip():
        filter_parts.append(f"申办方={filter_sponsor.strip()}")
    if filter_status:
        filter_parts.append(f"状态={filter_status}")
    if filter_phase:
        filter_parts.append(f"分期={','.join(filter_phase)}")
    if filter_parts:
        # 将筛选条件作为系统指令嵌入用户查询
        filter_text = "; ".join(filter_parts)
        enriched_query = f"[筛选条件: {filter_text}]\n{query.strip()}"
    else:
        enriched_query = query.strip()

    from openai import OpenAI
    client = OpenAI(
        api_key=api_key,
        base_url=base_url.strip() if base_url.strip() else None,
    )

    # ── 发起请求，展示结构化结果 ──
    result_placeholder = st.empty()
    with st.spinner("🧠 Agent is thinking and calling tools..."):
        result = run_agent(
            user_query=enriched_query,
            client=client,
            model=model,
            verbose=False,
        )

    st.divider()

    # ── 显示 Agent 回复 ──
    final = result.get("final_response", "")
    if final:
        st.subheader("📋 Agent Response")

        # 检查是否包含错误标记
        if "[凭证错误]" in final or "[限流]" in final or "[超时]" in final or "[工具调用失败]" in final:
            st.error(final)
        else:
            # 自动补全原文链接：将文本中的 NCT 编号和 PMID 转为可点击链接
            import re as _re
            linked = final
            linked = _re.sub(r"(?<!\[)(NCT\d{8})(?!\])",
                           r"[\1](https://clinicaltrials.gov/study/\1)", linked)
            linked = _re.sub(r"(?<!\[)(\b\d{8}\b)(?!\])(?=[^]]*(?:\[[^]]*\][^]]*)*$)",
                           r"[\1](https://pubmed.ncbi.nlm.nih.gov/\1/)", linked)
            st.markdown(linked)

        # Agent 调用轨迹（调试用，非数据可视化）
        trace = result.get("trace", [])
        with st.expander("🔍 Agent trace (tool calls & reasoning)", expanded=False):
            for i, step in enumerate(trace):
                st.markdown(f"**Step {i+1}**: `{step['tool']}(...)`")
                st.code(json.dumps(step["arguments"], ensure_ascii=False, indent=2)
                        if isinstance(step["arguments"], dict) else step["arguments"], language="json")
                # 截断显示结果
                preview = step.get("result_preview", "")
                if len(preview) > 500:
                    preview = preview[:500] + "..."
                st.code(preview, language="json")
                if i < len(trace) - 1:
                    st.divider()

    st.success("Done! 如有筛选条件，Agent 会自动在查询中应用。")

elif not query and not run_btn:
    st.info("输入查询并点击 Run Agent，或使用上方的快捷按钮。侧边栏的筛选条件会自动附加到查询中。")
