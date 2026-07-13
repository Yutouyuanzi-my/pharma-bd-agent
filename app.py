"""
药企 BD 竞争情报 Agent —— 三栏轻量化后台 Dashboard。

布局：左导航侧边栏 + 中间核心数据看板 + 右侧业务快捷栏
配色：极简浅灰白基底 + 暖橙主色 + 莫兰迪柔和色系（现代简约商务风）

运行方式：streamlit run app.py
"""

import os
import re
import json
from datetime import datetime, timedelta
from collections import Counter

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
    _CHINESE_SPONSOR_PATTERNS,
)
from agent import register_tool, run_agent
from openai import OpenAI

# ── 工具注册（供 智能助手 的 Agent 调用）──
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
        "properties": {"nct_id": {"type": "string", "description": "NCT ID like 'NCT04267848'"}},
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
    "description": "Search Chinese pharma company pipeline trials on ClinicalTrials.gov. Filters for Chinese sponsors.",
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
    "description": "Query CDE (China Center for Drug Evaluation) drug approval pipeline. Provides links and related Chinese trial info.",
    "parameters": {
        "type": "object",
        "properties": {
            "drug_name": {"type": "string", "description": "Drug name in Chinese or English, e.g. \"替雷利珠单抗\", \"tislelizumab\""},
            "milestone": {"type": "string", "description": "Optional: approval milestone filter"},
        },
        "required": ["drug_name"],
    },
})

# ── 客户端 ──
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
client = OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"), base_url=os.getenv("DEEPSEEK_BASE_URL"))

# ── 主题 ──
MORANDI = ["#d98841", "#a7b3a0", "#9bb0bd", "#cfa3a3", "#d8c3a5", "#b3a7b3", "#9bb0a8", "#c9b8a8"]

CSS = """
<style>
[data-testid="stAppViewContainer"] { background:#f4f1ec; }
[data-testid="stSidebar"] { background:#ffffff; border:none; min-width:260px !important; width:260px !important; }

/* ── 导航 radio ── */
[data-testid="stRadio"] { padding:8px 6px 16px; }
[data-testid="stRadio"] > label { font-size:15px !important; font-weight:600 !important; color:#3d3a36 !important; }
[data-testid="stRadio"] [role="radiogroup"] > label {
    display:flex !important; align-items:center !important; justify-content:center !important;
    padding:16px 14px !important; margin:8px 0 !important;
    border-radius:11px !important; border:1.5px solid transparent !important;
    font-size:17px !important; font-weight:650 !important; color:#3d3a36 !important;
    transition:all 0.15s ease !important; gap:10px !important;
}
[data-testid="stRadio"] [role="radiogroup"] > label:hover {
    background:#faf7f2 !important; border-color:#e8dfd2 !important;
}
[data-testid="stRadio"] [role="radiogroup"] > label[data-baseweb="radio-checked"] {
    background:linear-gradient(135deg,#fbe9dd 0%,#fdeee4 100%) !important;
    border-color:#d98841 !important; box-shadow:0 1px 6px rgba(217,136,65,0.12) !important;
    color:#1a1816 !important; font-weight:800 !important;
}

/* ── 指标卡 ── */
[data-testid="stMetric"] {
    background:#ffffff; border:0.5px solid #e8e3db; border-radius:14px;
    padding:20px 22px; box-shadow:none;
}
[data-testid="stMetric"] > div > div:nth-child(1) > div:nth-child(1) {
    font-size:34px !important; font-weight:800 !important; color:#111 !important;
}
[data-testid="stMetric"] > div > div:nth-child(1) > div:nth-child(2) {
    font-size:15px !important; font-weight:600 !important; color:#3d3a36 !important;
}
[data-testid="stMetric"] > div > div:nth-child(2) {
    font-size:13px !important; color:#6b6560 !important;
}

/* ── 视图标题 ── */
.viewhead { margin-bottom:24px; margin-top:8px; }
.viewhead h1 { font-size:30px; font-weight:800; color:#1a1816; margin:0 0 4px; letter-spacing:-0.3px; }
.viewhead .sub { font-size:14px; color:#6b6560; margin-top:4px; }

/* ── 通用卡片容器（左导航 / 右快捷栏）── */
/* 纯白底无框：仅靠白底色与页面浅米色(#f4f1ec)自然区隔，无边框无阴影 */
.card {
    background:#ffffff;
    border:none;
    border-radius:0;
    padding:28px 26px;
    box-shadow:none;
}
.nav-card { margin:0; height:100%; }
.right-card { margin:0; }
/* 卡片内大区块细分割线（仅区隔大区块，不分割单条按钮 / 列表项） */
.card-divider {
    height:0; border:0; border-top:1px solid #e6e0d6;
    margin:22px 0;
}
/* 卡片内板块标题（居中、加粗、加深、放大） */
.card-section {
    text-align:center;
    font-size:17px; font-weight:800; color:#2a2520;
    margin:2px 0 16px; letter-spacing:0.6px;
}

/* ── 导航品牌 ── */
.navbrand { text-align:center; font-size:24px; font-weight:900; color:#1a1816; padding:6px 0 16px; line-height:1.35; letter-spacing:-0.3px; }
.navbrand span { font-size:15px; font-weight:600; color:#4a4540; display:block; margin-top:4px; }

/* ── 右侧快捷栏 ── */
.righthead { text-align:center; font-size:20px; font-weight:800; color:#1a1816; margin-bottom:18px; letter-spacing:0.4px; }
.rlabel { text-align:center; font-size:16px; font-weight:800; color:#2a2520; margin:16px 0 12px; letter-spacing:0.5px; }
/* 提示 / 历史列表：深炭灰 + 加宽行高 */
.rhint, .rhist { text-align:center; font-size:15px; color:#3d3a36; padding:12px 4px; line-height:1.9; }
/* 快捷查询按钮 / 监测项按钮：浅暖橙底 + hover / 激活态强化识别 */
.stButton>button[key*="q_"], .stButton>button[key*="w_"] {
    font-size:15px !important; font-weight:600 !important;
    background:#fbeede !important; color:#8b5020 !important; border:1px solid #f0cfae !important;
    border-radius:11px !important; padding:15px 18px !important; margin:9px 0 !important;
    height:auto !important; white-space:normal !important; text-align:center !important;
    transition:all 0.15s ease !important;
}
.stButton>button[key*="q_"]:hover, .stButton>button[key*="w_"]:hover {
    background:#fad4be !important; border-color:#e8b98c !important;
}

/* ── 试验行 ── */
.trow { display:flex; gap:12px; padding:14px 6px; border-bottom:0.5px solid #ece8e0; align-items:flex-start; }
.trow .dot { width:9px; height:9px; border-radius:50%; margin-top:6px; flex:0 0 auto; }
.tmain a { color:#1a1816; font-size:15px; font-weight:700; text-decoration:none; line-height:1.5; }
.tmain a:hover { color:#d98841; }
.tmeta { font-size:13px; color:#5a554f; margin-top:4px; line-height:1.45; }
.chip { display:inline-block; background:#fbeede; color:#9a5f2a; font-size:11px; padding:2px 9px; border-radius:10px; margin-left:8px; font-weight:500; }

/* ── 通用按钮 ── */
.stButton>button[type="primary"] { border-radius:10px; padding:10px 28px; font-weight:600; font-size:14px; }

/* ── 区块间距 ── */
div[data-testid="stVerticalBlock"] > div[style*="flex-direction: column; gap: "] { gap:24px !important; }
div[data-testid="column"] > div[data-testid="stVerticalBlock"] > div[style*="flex-direction: column; gap: "] { gap:26px !important; }

/* ── 标题 h2/h3 ── */
h2, [data-testid="stMarkdownContainer"] > h2, h3, [data-testid="stMarkdownContainer"] > h3,
.markdown-text-container h2, .markdown-text-container h3 {
    font-size:19px !important; font-weight:750 !important; color:#2a2520 !important; margin-top:16px !important; margin-bottom:10px !important;
}

/* ── info/error ── */
[data-testid="stInfo"], [data-testid="stAlert"] { font-size:14px; padding:14px 18px; border-radius:10px; }
</style>
"""

st.set_page_config(page_title="药企 BD 竞品监测", page_icon="🏢", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)


# ── session 默认值 ──
for _k, _v in {
    "nav": "总览",
    "preset_query": "",
    "watchlist": [],
    "recent": [],
    "ov_cond": "",
    "overview_data": None,
    "landscape_data": None,
    "search_res": None,
    "monitor_data": None,
    "compare_data": None,
    "china_data": None,
    "cde_data": None,
    "assistant_result": None,
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ── 辅助函数 ──
def _is_chinese(sponsor: str) -> bool:
    sp = (sponsor or "").lower()
    return any(p.lower() in sp for p in _CHINESE_SPONSOR_PATTERNS)


def _risk_color(tags):
    if any("终止" in t or "安全" in t for t in tags):
        return "#c97b6e"
    if any(("突破性" in t or "招募" in t or "Phase 2 完成" in t or "First" in t) for t in tags):
        return "#7a9b6e"
    return "#9bb0bd"


def _push_recent(q: str):
    if q and q not in st.session_state.recent:
        st.session_state.recent.append(q)
        st.session_state.recent = st.session_state.recent[-10:]


def _add_watch(w: str):
    if w and w not in st.session_state.watchlist:
        st.session_state.watchlist.append(w)


def _linkify(text: str) -> str:
    text = re.sub(r"(?<!\[)(NCT\d{8})(?!\])", r"[\1](https://clinicaltrials.gov/study/\1)", text)
    text = re.sub(r"(?<!\[)(\b\d{8}\b)(?!\])", r"[\1](https://pubmed.ncbi.nlm.nih.gov/\1/)", text)
    return text


def _chart(fig):
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="-apple-system, 'PingFang SC', sans-serif", size=14, color="#3d3a36"),
        margin=dict(l=16, r=16, t=16, b=16),
        xaxis=dict(gridcolor="#ece8e0", zeroline=False, tickfont=dict(size=13, color="#4a4540")),
        yaxis=dict(gridcolor="#ece8e0", zeroline=False, tickfont=dict(size=13, color="#4a4540")),
    )
    st.plotly_chart(fig, use_container_width=True)


def _trial_row(s: dict):
    nct = s.get("nct_id", "")
    link = s.get("nct_link", f"https://clinicaltrials.gov/study/{nct}")
    # 兼容两种字段命名：完整 study（brief_title/overall_status）与精简 trial（title/status）
    title = (s.get("brief_title") or s.get("title") or "")[:72]
    status = s.get("overall_status") or s.get("status") or ""
    phase = s.get("phase", "") or "-"
    date = s.get("last_update_post_date") or s.get("study_first_post_date") or ""
    tags = s.get("risk_tags", []) or []
    chip = "".join(f'<span class="chip">{t}</span>' for t in tags)
    col = _risk_color(tags)
    html = (
        f'<div class="trow"><span class="dot" style="background:{col}"></span>'
        f'<div class="tmain"><a href="{link}" target="_blank">{title}</a>'
        f'<div class="tmeta">{nct} · {phase} · {status} · {date}{chip}</div></div></div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def _viewhead(title, sub):
    return f'<div class="viewhead"><h1>{title}</h1><div class="sub">{sub}</div></div>'


# ── 各视图渲染 ──
def render_overview():
    # 懒加载：只在用户点「生成看板」时才导入重库，首页秒开
    import pandas as pd
    import plotly.express as px
    import plotly.graph_objects as go

    st.markdown(_viewhead("总览", "一键聚合治疗领域的试验规模、竞争格局与近期动态"), unsafe_allow_html=True)
    cond = st.text_input("监测主题（治疗领域 / 靶点）", value=st.session_state.ov_cond,
                         key="ov_input", placeholder="如 NSCLC, PD-1, CAR-T")
    if st.button("生成看板", type="primary", key="ov_btn"):
        if not cond.strip():
            st.error("请输入监测主题")
        else:
            with st.spinner("聚合临床试验数据..."):
                landscape = analyze_competitive_landscape(cond.strip())
                recent = monitor_recent_changes(cond.strip(), since_days=30)
            st.session_state.overview_data = {"landscape": landscape, "recent": recent, "cond": cond.strip()}
            st.session_state.ov_cond = cond.strip()
            _push_recent(cond.strip())
    data = st.session_state.overview_data
    if not data:
        st.info("输入监测主题并点击「生成看板」生成数据看板。")
        return
    landscape, recent = data["landscape"], data["recent"]
    if "error" in landscape:
        st.error(landscape["error"])
        return

    studies = [s for s in recent.get("studies", [])] if "error" not in recent else []
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    week = [s for s in studies if (s.get("last_update_post_date") or s.get("study_first_post_date") or "") >= cutoff]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("总试验", landscape.get("total_trials", 0))
    c2.metric("活跃试验", landscape.get("active_trials", 0))
    c3.metric("近30天新增", len(studies))
    c4.metric("本周新增", len(week))

    top = landscape.get("top_sponsors", [])
    if top:
        df = pd.DataFrame([{"申办方": t["sponsor"][:14], "试验数": t["trial_count"]} for t in top]).sort_values("试验数")
        _chart(px.bar(df, x="试验数", y="申办方", orientation="h", color_discrete_sequence=["#d98841"]))

    pd_ = landscape.get("phase_distribution", {})
    phases = {p: len(v) for p, v in pd_.items() if v}
    if phases:
        dfp = pd.DataFrame([{"阶段": k, "试验数": v} for k, v in phases.items()])
        _chart(px.bar(dfp, x="阶段", y="试验数", color="阶段", color_discrete_sequence=MORANDI))

    if studies:
        dates = [ (s.get("last_update_post_date") or s.get("study_first_post_date") or "")[:10] for s in studies ]
        dates = [d for d in dates if d]
        if dates:
            cnt = Counter(dates)
            sd = sorted(cnt.keys())
            fig = go.Figure(go.Scatter(x=sd, y=[cnt[d] for d in sd], mode="lines+markers",
                                       line=dict(color="#d98841", width=2), fill="tozeroy",
                                       fillcolor="rgba(217,136,65,0.12)"))
            _chart(fig)

    st.markdown("### 近期重要更新")
    for s in studies[:10]:
        _trial_row(s)

    if st.button("★ 加入我的监测", key="ov_watch"):
        _add_watch(data["cond"])


def render_landscape():
    import pandas as pd
    import plotly.express as px

    st.markdown(_viewhead("竞争格局", "分析治疗领域的竞争密度：主要玩家与阶段分布"), unsafe_allow_html=True)
    cond = st.text_input("治疗领域", value=st.session_state.ov_cond, key="l_cond")
    sponsor = st.text_input("聚焦申办方（可选）", key="l_sp")
    if st.button("生成分析", type="primary", key="l_btn"):
        if not cond.strip():
            st.error("请输入治疗领域")
        else:
            with st.spinner("分析竞争格局..."):
                res = analyze_competitive_landscape(cond.strip(), sponsor=sponsor or None)
            st.session_state.landscape_data = res
            st.session_state.ov_cond = cond.strip()
            _push_recent(cond.strip())
    res = st.session_state.landscape_data
    if not res:
        st.info("输入治疗领域生成分析。")
        return
    if "error" in res:
        st.error(res["error"])
        return

    cn = sum(1 for t in res.get("top_sponsors", []) if _is_chinese(t["sponsor"]))
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("总试验", res.get("total_trials", 0))
    m2.metric("活跃试验", res.get("active_trials", 0))
    m3.metric("主要申办方", len(res.get("top_sponsors", [])))
    m4.metric("中国药企", cn)

    top = res.get("top_sponsors", [])
    if top:
        df = pd.DataFrame([{"申办方": t["sponsor"][:14], "试验数": t["trial_count"]} for t in top]).sort_values("试验数")
        _chart(px.bar(df, x="试验数", y="申办方", orientation="h", color_discrete_sequence=["#d98841"]))

    pd_ = res.get("phase_distribution", {})
    phases = {p: len(v) for p, v in pd_.items() if v}
    if phases:
        dfp = pd.DataFrame([{"阶段": k, "试验数": v} for k, v in phases.items()])
        _chart(px.bar(dfp, x="阶段", y="试验数", color="阶段", color_discrete_sequence=MORANDI))

    if st.button("★ 加入我的监测", key="l_watch"):
        _add_watch(cond.strip())

    if st.button("生成 AI 竞争简报", key="l_ai"):
        with st.spinner("AI 撰写中..."):
            out = run_agent(
                f"请用中文撰写 {cond.strip()} 竞争格局简报：主要玩家管线布局、各阶段竞争密度、"
                f"值得关注的趋势或空白领域、给 BD 团队的策略建议。",
                client=client, model=MODEL, verbose=False)
        final = out.get("final_response", "")
        if final:
            st.markdown(_linkify(final))
        else:
            st.info("未能生成简报。")


def render_search():
    st.markdown(_viewhead("试验检索", "按疾病 / 靶点 / 公司检索 ClinicalTrials.gov"), unsafe_allow_html=True)
    q = st.text_input("疾病或关键词", key="s_q", placeholder="NSCLC, CAR-T, PD-1...")
    sponsor = st.text_input("申办方（可选）", key="s_sp")
    status = st.selectbox("状态（可选）", ["", "RECRUITING", "ACTIVE_NOT_RECRUITING", "COMPLETED",
                                           "TERMINATED", "WITHDRAWN"], key="s_st")
    if st.button("检索", type="primary", key="s_btn"):
        if not q.strip():
            st.error("请输入关键词")
        else:
            with st.spinner("检索中..."):
                res = search_clinical_trials(q.strip(), sponsor=sponsor or None,
                                             status=status or None, page_size=15)
            st.session_state.search_res = res
            _push_recent(q.strip())
    res = st.session_state.search_res
    if not res:
        st.info("输入关键词检索。")
        return
    if "error" in res:
        st.error(res["error"])
        return
    studies = res.get("studies", [])
    st.markdown(f"**共 {res.get('total_count', 0)} 条结果**")
    for s in studies:
        _trial_row(s)
    if studies:
        nct = st.selectbox("查看试验详情", [s["nct_id"] for s in studies], key="s_detail")
        d = get_trial_detail(nct)
        if "error" not in d:
            st.markdown(f"### {d.get('brief_title')}")
            st.markdown(f"**申办方**: {d.get('sponsor')}  ")
            st.markdown(f"**阶段**: {d.get('phase') or '-'} · **状态**: {d.get('overall_status')}  ")
            st.markdown(f"[查看原始协议]({d.get('nct_link')})")
            if d.get("brief_summary"):
                st.markdown(d["brief_summary"])
            if d.get("primary_outcomes"):
                st.markdown("**主要终点**: " + "; ".join(d["primary_outcomes"]))


def render_monitor():
    import plotly.graph_objects as go

    st.markdown(_viewhead("每日监测", "追踪治疗领域近期新增 / 更新试验"), unsafe_allow_html=True)
    cond = st.text_input("治疗领域", value=st.session_state.ov_cond, key="m_cond")
    days = st.number_input("监测天数", min_value=1, max_value=90, value=7, key="m_days")
    if st.button("监测", type="primary", key="m_btn"):
        with st.spinner("监测中..."):
            res = monitor_recent_changes((cond.strip() or "cancer"), since_days=days)
        st.session_state.monitor_data = res
        if cond.strip():
            _push_recent(cond.strip())
    res = st.session_state.monitor_data
    if not res:
        st.info("输入治疗领域开始监测。")
        return
    if "error" in res:
        st.error(res["error"])
        return
    st.metric("新增 / 更新", res.get("new_and_updated_count", 0))
    studies = res.get("studies", [])
    if studies:
        dates = [(s.get("last_update_post_date") or s.get("study_first_post_date") or "")[:10] for s in studies]
        dates = [d for d in dates if d]
        if dates:
            cnt = Counter(dates)
            sd = sorted(cnt.keys())
            fig = go.Figure(go.Scatter(x=sd, y=[cnt[d] for d in sd], mode="lines+markers",
                                       line=dict(color="#d98841", width=2), fill="tozeroy",
                                       fillcolor="rgba(217,136,65,0.12)"))
            _chart(fig)
    for s in studies[:30]:
        _trial_row(s)


def render_compare():
    st.markdown(_viewhead("竞品对比", "并排对比多个试验：设计 / 终点 / 竞争定位"), unsafe_allow_html=True)
    ids = st.text_area("输入 NCT ID（逗号分隔，最多 5 个）", key="c_ids",
                       placeholder="NCT04267848, NCT04191356")
    if st.button("对比", type="primary", key="c_btn"):
        ncts = [x.strip() for x in ids.split(",") if x.strip()]
        if len(ncts) < 2:
            st.error("至少输入 2 个 NCT ID")
        else:
            with st.spinner("对比中..."):
                res = compare_trials_side_by_side(ncts[:5], llm_client=client, model=MODEL)
            st.session_state.compare_data = res
    res = st.session_state.compare_data
    if not res:
        st.info("输入至少 2 个 NCT ID 对比。")
        return
    comp = res.get("trials_comparison", [])
    if not comp:
        st.error("未获取到对比数据。")
        return
    fields = [
        ("申办方", "sponsor"), ("阶段", "phase"), ("状态", "status"),
        ("条件", "conditions"), ("干预", "interventions"), ("主要终点", "primary_outcomes"),
    ]
    head = "".join(f"<th>{f[0]}</th>" for f in fields)
    rows = ""
    for t in comp:
        cells = ""
        for _, key in fields:
            v = t.get(key, "")
            if isinstance(v, list):
                v = "; ".join(map(str, v))
            cells += f"<td>{v}</td>"
        link = t.get("nct_link", "")
        rows += f'<tr><td><a href="{link}" target="_blank">{t.get("nct_id")}</a></td>{cells}</tr>'
    st.markdown(
        f'<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:12px">'
        f'<thead><tr><th>NCT</th>{head}</tr></thead><tbody>{rows}</tbody></table></div>',
        unsafe_allow_html=True,
    )
    if res.get("llm_comparison"):
        st.markdown("### AI 对比分析")
        st.markdown(_linkify(res["llm_comparison"]))


def render_china():
    st.markdown(_viewhead("中国管线", "中国药企管线 + CDE 审批进度"), unsafe_allow_html=True)
    tab1, tab2 = st.tabs(["管线检索", "CDE 审批"])
    with tab1:
        cond = st.text_input("治疗领域", value=st.session_state.ov_cond, key="cn_cond")
        if st.button("检索中国管线", type="primary", key="cn_btn"):
            with st.spinner("检索中..."):
                res = search_chinese_pipeline(cond.strip())
            st.session_state.china_data = res
            if cond.strip():
                _push_recent(cond.strip())
        res = st.session_state.china_data
        if res and "error" not in res:
            st.metric("中国药企试验", res.get("total_chinese_trials", 0))
            for sp in res.get("chinese_sponsors", []):
                st.markdown(f"**{sp['sponsor']}** · {sp['trial_count']} 项")
                for t in sp["trials"]:
                    _trial_row(t)
            if res.get("chictr_search_link"):
                st.markdown(f"[在 ChiCTR 检索 {res.get('condition')}]({res['chictr_search_link']})")
    with tab2:
        drug = st.text_input("药品名（中 / 英）", key="cde_drug")
        if st.button("查询 CDE", type="primary", key="cde_btn"):
            with st.spinner("查询中..."):
                res = search_cde_approvals(drug.strip())
            st.session_state.cde_data = res
        res = st.session_state.cde_data
        if res:
            st.markdown(f"[CDE 数据查询：{res['drug_name']}]({res['cde_search_link']})  ")
            st.markdown(f"[药物临床试验登记平台]({res['clinical_trial_link']})")
            for k, v in res.get("quick_links", {}).items():
                st.markdown(f"- [{k}]({v})")
            if res.get("related_chinese_trials"):
                st.markdown("**关联中国试验**")
                for t in res["related_chinese_trials"]:
                    _trial_row(t)


def render_assistant():
    st.markdown(_viewhead("智能助手", "自由提问，Agent 自动调用工具检索并整合"), unsafe_allow_html=True)
    preset = st.session_state.preset_query
    query = st.text_area("输入查询", value=preset, key="a_query", height=100)
    if query != preset:
        st.session_state.preset_query = ""
    if st.button("▶ 运行 Agent", type="primary", key="a_btn"):
        if not query.strip():
            st.error("请输入查询")
        elif not os.getenv("DEEPSEEK_API_KEY"):
            st.error("未在 .env 中找到 DEEPSEEK_API_KEY。")
        else:
            _push_recent(query.strip())
            with st.spinner("Agent 思考中..."):
                result = run_agent(query.strip(), client=client, model=MODEL,
                                   max_tool_rounds=8, verbose=False)
            st.session_state.assistant_result = result
    result = st.session_state.assistant_result
    if not result:
        st.info("输入查询并运行 Agent，或使用右侧快捷查询。")
        return
    final = result.get("final_response", "")
    if final:
        if any(x in final for x in ("[凭证错误]", "[限流]", "[超时]", "[工具调用失败]")):
            st.error(final)
        else:
            st.markdown(_linkify(final))
        with st.expander("Agent trace（工具调用与推理）", expanded=False):
            for i, step in enumerate(result.get("trace", [])):
                st.markdown(f"**Step {i+1}**: `{step['tool']}`")
                st.json(step.get("arguments", {}))
    else:
        st.info("未获得结果。")


# ── 右侧业务快捷栏 ──
def render_right_bar():
    st.markdown('<div class="card right-card">', unsafe_allow_html=True)
    st.markdown('<div class="righthead">业务快捷</div>', unsafe_allow_html=True)
    st.markdown('<div class="card-divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="card-section">快捷查询</div>', unsafe_allow_html=True)
    quick = {"CAR-T 细胞疗法": "CAR-T", "NSCLC 非小细胞肺癌": "NSCLC",
             "PD-1 / PD-L1": "PD-1", "ADC 抗体偶联药物": "ADC"}
    for label, q in quick.items():
        if st.button(label, key=f"q_{q}", use_container_width=True):
            st.session_state.preset_query = f"分析 {q} 领域的竞争格局，并列出近期重要更新"
            # 用延迟跳转：设中间变量，在 radio 渲染前消费（避免改已绑定 widget 的值）
            st.session_state._pending_nav = "智能助手"
            st.rerun()
    st.markdown('<div class="card-divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="card-section">我的监测</div>', unsafe_allow_html=True)
    if not st.session_state.watchlist:
        st.markdown('<div class="rhint">暂无监测项</div>', unsafe_allow_html=True)
    for i, w in enumerate(st.session_state.watchlist):
        if st.button(f"● {w}", key=f"w_{i}", use_container_width=True):
            st.session_state._pending_nav = "总览"
            st.session_state._pending_cond = w
            st.rerun()
    st.markdown('<div class="card-divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="card-section">最近查询</div>', unsafe_allow_html=True)
    for r in st.session_state.recent[::-1][:6]:
        st.markdown(f'<div class="rhist">{r}</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)


# ── 主结构 ──
# 消费右侧按钮的延迟跳转（必须在 radio widget key="nav" 渲染之前）
if st.session_state.get("_pending_nav"):
    st.session_state.nav = st.session_state.pop("_pending_nav")
if st.session_state.get("_pending_cond"):
    st.session_state.ov_cond = st.session_state.pop("_pending_cond")

with st.sidebar:
    st.markdown('<div class="card nav-card">', unsafe_allow_html=True)
    st.markdown('<div class="navbrand">BD 情报<br><span>药企竞品监测</span></div>', unsafe_allow_html=True)
    st.markdown('<div class="card-divider"></div>', unsafe_allow_html=True)
    NAV = ["总览", "竞争格局", "试验检索", "每日监测", "竞品对比", "中国管线", "智能助手"]
    view = st.radio("导航", NAV, index=NAV.index(st.session_state.nav), key="nav",
                    label_visibility="collapsed")
    st.markdown('</div>', unsafe_allow_html=True)

center, right = st.columns([4, 1.1])
with right:
    render_right_bar()
with center:
    if view == "总览":
        render_overview()
    elif view == "竞争格局":
        render_landscape()
    elif view == "试验检索":
        render_search()
    elif view == "每日监测":
        render_monitor()
    elif view == "竞品对比":
        render_compare()
    elif view == "中国管线":
        render_china()
    elif view == "智能助手":
        render_assistant()
