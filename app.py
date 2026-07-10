"""
药企 BD 竞争情报 Agent 的 Streamlit 前端界面。

运行方式：streamlit run app.py

这个文件负责：
1. 注册所有可用工具（供 Agent 调用）
2. 渲染 Streamlit UI（输入框、按钮、结果展示）
3. 处理用户交互（点击按钮、输入查询、调用 Agent）
"""

import os
import streamlit as st
import json
from dotenv import load_dotenv

# 加载 .env 中的环境变量（API Key / 自定义端点 / 模型名）
load_dotenv()

# ── 工具导入和注册 ──

# 从 tools.py 导入所有工具函数
from tools import (
    search_clinical_trials,
    get_trial_detail,
    search_pubmed,
    analyze_competitive_landscape,
    monitor_recent_changes,
    compare_trials_side_by_side,
)
# 从 agent.py 导入工具注册函数和 Agent 运行器
from agent import register_tool, run_agent

# 注册工具 1：搜索临床试验
# 功能：按疾病条件、申办方、状态搜索 ClinicalTrials.gov
register_tool("search_clinical_trials", search_clinical_trials, {
    "description": "Search ClinicalTrials.gov by condition, sponsor/company, and status.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Disease, condition, or keyword, e.g. 'NSCLC' or 'CAR-T'",
            },
            "sponsor": {
                "type": "string",
                "description": "Sponsor/company name, e.g. 'Roche', 'AstraZeneca', 'Bristol-Myers Squibb'",
            },
            "status": {
                "type": "string",
                "description": "Trial status filter: RECRUITING, ACTIVE_NOT_RECRUITING, COMPLETED, etc.",
            },
            "page_size": {
                "type": "integer",
                "description": "Number of results (max 20)",
                "default": 10,
            },
        },
        "required": ["query"],
    },
})

# 注册工具 2：获取试验详情
# 功能：根据 NCT ID 获取单个试验的完整协议信息
register_tool("get_trial_detail", get_trial_detail, {
    "description": "Get full protocol details for a specific study by NCT ID.",
    "parameters": {
        "type": "object",
        "properties": {
            "nct_id": {
                "type": "string",
                "description": "NCT ID like 'NCT04267848'",
            },
        },
        "required": ["nct_id"],
    },
})

# 注册工具 3：竞争格局分析
# 功能：分析某个治疗领域的竞争格局（按申办方、阶段分组）
register_tool("analyze_competitive_landscape", analyze_competitive_landscape, {
    "description": "Analyze the competitive landscape for a therapeutic area. Groups trials by sponsor, phase, and produces a structured CI report.",
    "parameters": {
        "type": "object",
        "properties": {
            "condition": {
                "type": "string",
                "description": "Therapeutic area or condition, e.g. 'NSCLC', 'HER2+ breast cancer'",
            },
            "sponsor": {
                "type": "string",
                "description": "Optional: Focus on a specific sponsor/company to see their position vs competitors",
            },
        },
        "required": ["condition"],
    },
})

# 注册工具 4：监测近期变更
# 功能：查找某个治疗领域最近 N 天内的新增或更新试验（每日监测核心工具）
register_tool("monitor_recent_changes", monitor_recent_changes, {
    "description": "Monitor recent changes: find new or updated trials in a therapeutic area. Core daily monitoring tool for BD.",
    "parameters": {
        "type": "object",
        "properties": {
            "condition": {
                "type": "string",
                "description": "Therapeutic area or condition to monitor",
            },
            "since_days": {
                "type": "integer",
                "description": "How many days back to check (default 7 for weekly, 1 for daily)",
                "default": 7,
            },
        },
        "required": ["condition"],
    },
})

# 注册工具 5：并排对比试验
# 功能：对比最多 5 个试验（申办方、阶段、设计、结果、竞争定位）
register_tool("compare_trials_side_by_side", compare_trials_side_by_side, {
    "description": "Compare up to 5 trials side by side: sponsor, phase, design, outcomes, competitive positioning.",
    "parameters": {
        "type": "object",
        "properties": {
            "nct_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of NCT IDs to compare, e.g. ['NCT04267848', 'NCT04191356']",
            },
        },
        "required": ["nct_ids"],
    },
})

# 注册工具 6：搜索 PubMed 文献
# 功能：搜索医学主题的科学文献（用于补充科学背景）
register_tool("search_pubmed", search_pubmed, {
    "description": "Search PubMed for scientific articles on a medical topic.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "PubMed search query",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of articles",
                "default": 5,
            },
        },
        "required": ["query"],
    },
})


# ── 页面配置 ──

st.set_page_config(
    page_title="Pharma BD Intelligence Agent",
    page_icon="🏢",
    layout="wide",  # 宽屏布局
)

st.title("🏢 Pharma BD Competitive Intelligence Agent")
st.markdown(
    "Monitor competitor pipelines, analyze clinical trial landscapes, and get daily briefings — "
    "all powered by an AI agent that searches ClinicalTrials.gov and PubMed."
)

# ── 侧边栏：API Key 和设置 ──

with st.sidebar:
    st.header("Settings")

    # API Key：优先用 .env 中的值预填，用户也可在界面手动覆盖
    api_key = st.text_input(
        "API Key (OpenAI / DeepSeek)",
        type="password",
        value=os.getenv("OPENAI_API_KEY", ""),
        help="支持 OpenAI 及任何兼容 OpenAI 协议的端点（如 DeepSeek）。也可在 .env 中配置。",
    )

    # 模型选择：内置常见 OpenAI 模型，并额外支持自定义（DeepSeek 为 deepseek-chat）
    MODEL_CHOICES = ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "deepseek-chat"]
    env_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    if env_model and env_model not in MODEL_CHOICES:
        MODEL_CHOICES = MODEL_CHOICES + [env_model]
    try:
        model_idx = MODEL_CHOICES.index(env_model)
    except ValueError:
        model_idx = 0

    model = st.selectbox("Model", MODEL_CHOICES, index=model_idx)

    # 自定义模型名：若填写则覆盖上方选择（用于任意兼容模型）
    custom_model = st.text_input(
        "自定义模型名（可选，留空则用上方选择）",
        value="",
        help="例如 deepseek-reasoner、qwen-max 等任意兼容模型",
    )
    if custom_model.strip():
        model = custom_model.strip()

    # 自定义 API Base URL：用于 DeepSeek 等兼容端点
    base_url = st.text_input(
        "API Base URL（可选，自定义端点用）",
        value=os.getenv("OPENAI_BASE_URL", ""),
        help="DeepSeek 填 https://api.deepseek.com ；留空则用 OpenAI 官方端点",
    )

    st.divider()
    
    # BD 使用场景示例（帮助用户理解如何使用）
    st.markdown("### 💼 BD Use Cases")
    st.markdown(
        "**Competitive Landscape**\n"  # 竞争格局
        '- "Show me the competitive landscape for NSCLC"\n'
        '- "What is Roche doing in breast cancer?"\n'
        '- "Compare Pfizer vs Merck in immuno-oncology"\n\n'
        "**Daily Monitoring**\n"  # 每日监测
        '- "What changed in the last week for CAR-T?"\n'
        '- "Any new GLP-1 trials this month?"\n\n'
        "**Deep Dive**\n"  # 深度分析
        '- "Compare NCT04267848 and NCT04191356"\n'
        '- "What trials does AstraZeneca have for EGFR mutant NSCLC?"'
    )

# ── 快捷操作按钮 ──

st.markdown("### 快捷操作")
# 创建 4 个并排按钮
col_a, col_b, col_c, col_d = st.columns(4)
with col_a:
    preset1 = st.button("📊 NSCLC 竞争格局", use_container_width=True)
with col_b:
    preset2 = st.button("🔍 AstraZeneca 在做什么", use_container_width=True)
with col_c:
    preset3 = st.button("📅 CAR-T 本周更新", use_container_width=True)
with col_d:
    preset4 = st.button("⚖️ 对比两个试验", use_container_width=True)

# ── 查询输入框 ──

# 输入框的占位符文本（提示用户如何输入）
query_placeholder = (
    "e.g.: 分析一下 NSCLC 领域的竞争格局，重点关注 PD-1/PD-L1 药物的临床试验分布。\n"
    "或者：帮我看一下这周有哪些新的 CAR-T 临床试验登记了。"
)

# 根据用户点击的快捷按钮，设置默认查询
default_query = ""
if preset1:
    default_query = "分析 NSCLC 的竞争格局，列出主要药企的试验分布"
elif preset2:
    default_query = "AstraZeneca 在 NSCLC 领域有哪些临床试验？各处于什么阶段？"
elif preset3:
    default_query = "过去一周 CAR-T 疗法有什么新的临床试验？请列出新增和更新的试验"
elif preset4:
    default_query = "帮我对比一下 NCT04267848 和 NCT04191356，从试验设计、入排标准和竞争定位角度分析"

# 文本输入区域（多行）
query = st.text_area(
    "输入你的查询",
    value=default_query,
    placeholder=query_placeholder,
    height=100,
)

# 运行按钮
col1, col2 = st.columns([1, 5])
with col1:
    run_btn = st.button("▶ Run Agent", type="primary", use_container_width=True)

# ── 结果显示区域 ──

if run_btn:
    # 输入验证
    if not api_key:
        st.error("Please enter your OpenAI API key in the sidebar.")
        st.stop()
    if not query.strip():
        st.error("Please enter a query.")
        st.stop()

    # 创建 OpenAI 客户端（兼容任意 OpenAI 协议端点，通过 base_url 切换）
    from openai import OpenAI
    client = OpenAI(
        api_key=api_key,
        base_url=base_url.strip() if base_url.strip() else None,
    )

    # 调用 Agent（带 loading 动画）
    with st.spinner("🧠 Agent is thinking and calling tools..."):
        result = run_agent(
            user_query=query.strip(),
            client=client,
            model=model,
            verbose=False,  # 不在 Streamlit 中打印详细日志
        )

    # 显示分隔线
    st.divider()
    st.subheader("📋 Agent Response")

    # 显示 Agent 的最终回复（Markdown 格式）
    st.markdown(result["final_response"])

    # 可展开的工具调用轨迹（用于调试和理解 Agent 决策过程）
    with st.expander("🔍 Agent trace (tool calls & reasoning)", expanded=False):
        for i, step in enumerate(result.get("trace", [])):
            st.markdown(f"**Step {i+1}**: `{step['tool']}(...)`")
            # 显示工具调用的参数
            st.code(
                json.dumps(step["arguments"], ensure_ascii=False, indent=2)
                if isinstance(step["arguments"], dict)
                else step["arguments"],
                language="json",
            )
            # 显示工具返回的结果（预览）
            st.code(step["result_preview"], language="json")
            if i < len(result["trace"]) - 1:
                st.divider()

    st.success("Done! Copy the briefing or run a new query.")

elif not query and not run_btn:
    # 初始状态提示
    st.info("输入查询并点击 Run Agent，或使用上方快捷按钮。")
