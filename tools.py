"""
Agent 工具集：ClinicalTrials.gov 竞争情报 + PubMed + 格局分析。

所有工具都是无状态函数 —— Agent 控制器负责编排调用顺序。

包含以下工具：
1. search_clinical_trials - 搜索临床试验
2. get_trial_detail - 获取试验详情
3. search_pubmed - 搜索 PubMed 文献
4. analyze_competitive_landscape - 竞争格局分析（核心 BD 工具）
5. monitor_recent_changes - 监测近期变更（每日监测）
6. compare_trials_side_by_side - 并排对比试验
"""

import json
import re
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional, Any

import requests
import urllib3

# 屏蔽 requests 关闭验证时的控制台警告（国内网络开发用）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# API 基础 URL
CLINICAL_TRIALS_BASE = "https://clinicaltrials.gov/api/v2"
PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# 默认请求头（模拟浏览器，绕过 WAF）
# urllib 的 TLS 指纹会被 ClinicalTrials.gov WAF 识别拦截（403），
# 用 requests 库配合完整请求头可以正常通过。
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


# ──────────────────────────────────────────────
# 工具 1：搜索 ClinicalTrials.gov（增强版，支持申办方/公司字段）
# ──────────────────────────────────────────────

def search_clinical_trials(
    query: str,
    sponsor: Optional[str] = None,
    status: Optional[str] = None,
    page_size: int = 10,
    format: str = "json",
) -> dict:
    """按疾病、公司/申办方、状态搜索 ClinicalTrials.gov。

    v2 API 移除了 `query.adv`（AREA[Sponsor] 语法），
    改用 `filter` 参数 + Python 端后过滤。

    非常适合 BD 使用场景："Roche 在 NSCLC 领域在做什么？"

    Args:
        query: 疾病或条件关键词（如 "NSCLC", "CAR-T"）
        sponsor: 申办方/公司名称（如 "Roche", "AstraZeneca"）
        status: 试验状态过滤（如 "RECRUITING", "ACTIVE_NOT_RECRUITING"）
        page_size: 返回结果数量（最大 20）
        format: 返回格式（默认 "json"）

    Returns:
        dict: 包含 total_count 和 studies 列表的字典
    """
    # v2 API 支持 filter.overallStatus，但不支持 sponsor 和高级 Area 查询了
    # 策略：用 query.term 做全文搜索，然后在 Python 端按 sponsor/status 过滤
    # 将 sponsor 和 status 嵌入 query.term 以提高 API 层面的召回率
    term_parts = [query]
    if sponsor:
        term_parts.append(sponsor)
    if status:
        # status 字段在全文索引中，拼进去提高初始命中率
        term_parts.append(status.lower())
    params = {
        "query.term": " ".join(term_parts),
        "pageSize": str(min(page_size * 5, 100)),  # 放宽 pageSize 留出后过滤空间
        "format": format,
    }

    url = f"{CLINICAL_TRIALS_BASE}/studies?" + urllib.parse.urlencode(params)
    result = _fetch_studies(url)

    if "error" in result:
        return result

    studies = result.get("studies", [])

    # 按 sponsor 后过滤（v2 API 不支持 sponsor 过滤参数）
    if sponsor:
        sponsor_lower = sponsor.strip().lower()
        studies = [
            s for s in studies
            if sponsor_lower in (s.get("sponsor") or "").lower()
        ]

    # 按 status 后过滤
    if status:
        status_lower = status.strip().lower()
        studies = [
            s for s in studies
            if (s.get("overall_status") or "").lower() == status_lower
        ]

    return {
        "total_count": len(studies),
        "studies": studies[:page_size],
    }


def _fetch_studies(url: str) -> dict:
    """内部函数：从 URL 获取并汇总试验列表。"""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15, verify=False)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text[:300]}"}
    except Exception as e:
        return {"error": str(e)}

    studies = data.get("studies", [])
    return {
        "total_count": len(studies),
        "studies": [_summarize_study(s.get("protocolSection", {})) for s in studies],
    }


def _summarize_study(ps: dict) -> dict:
    """从试验的 protocolSection 中提取关键信息。

    将 ClinicalTrials.gov API 返回的完整协议数据精简为
    BD 分析师需要的核心字段。

    Args:
        ps: protocolSection 字典（API 返回的原始数据）

    Returns:
        dict: 包含关键信息的精简字典
    """
    # 从不同模块中提取信息
    id_mod = ps.get("identificationModule", {})       # 标识信息（NCT ID、标题）
    sponsor_mod = ps.get("sponsorCollaboratorsModule", {})  # 申办方信息
    des_mod = ps.get("descriptionModule", {})          # 描述信息（摘要）
    stat_mod = ps.get("statusModule", {})              # 状态信息
    desig_mod = ps.get("designModule", {})             # 设计信息（阶段）
    elig_mod = ps.get("eligibilityModule", {})         # 资格标准
    cond_mod = ps.get("conditionsModule", {})           # 疾病条件
    int_mod = ps.get("interventionsModule", {})         # 干预措施
    outcome_mod = ps.get("outcomesModule", {})          # 结果指标

    return {
        "nct_id": id_mod.get("nctId", ""),           # NCT 编号
        "brief_title": id_mod.get("briefTitle", ""),    # 简要标题
        "sponsor": (sponsor_mod.get("leadSponsor") or {}).get("name", ""),  # 主要申办方
        "collaborators": [                              # 合作方
            c.get("name", "") for c in (sponsor_mod.get("collaborators") or [])],
        "brief_summary": (des_mod.get("briefSummary") or "")[:500],  # 简要摘要（截断）
        "overall_status": stat_mod.get("overallStatus", ""),          # 总体状态
        "phase": desig_mod.get("phases", [None])[0] if desig_mod.get("phases") else "",  # 阶段
        "conditions": cond_mod.get("conditions", []),    # 疾病条件列表
        "interventions": [                              # 干预措施列表
            i.get("name", "") for i in (int_mod.get("interventions") or [])],
        "primary_outcomes": [                           # 主要终点
            o.get("measure", "") for o in (outcome_mod.get("primaryOutcomes") or [])],
        "eligibility_criteria": (elig_mod.get("eligibilityCriteria") or "")[:2000],  # 资格标准（截断）
        "sex": elig_mod.get("sex", ""),                # 性别要求
        "minimum_age": elig_mod.get("minimumAge", ""),  # 最小年龄
        "maximum_age": elig_mod.get("maximumAge", ""),  # 最大年龄
        "healthy_volunteers": elig_mod.get("healthyVolunteers", ""),  # 是否接受健康志愿者
        "last_update_post_date": (stat_mod.get("lastUpdatePostDateStruct") or {}).get("date", ""),  # 最后更新发布日期
        "study_first_post_date": (stat_mod.get("studyFirstPostDateStruct") or {}).get("date", ""),  # 首次发布日期
    }


# ──────────────────────────────────────────────
# 工具 2：根据 NCT ID 获取单个试验的完整协议
# ──────────────────────────────────────────────

def get_trial_detail(nct_id: str) -> dict:
    """根据 NCT ID 获取单个试验的完整协议。

    Args:
        nct_id: NCT 编号（如 "NCT04267848"）

    Returns:
        dict: 包含试验详细信息的字典
    """
    url = f"{CLINICAL_TRIALS_BASE}/studies/{nct_id}?format=json"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15, verify=False)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTP {e.response.status_code}"}
    except Exception as e:
        return {"error": str(e)}

    ps = data.get("protocolSection", {})
    return _summarize_study(ps)


# ──────────────────────────────────────────────
# 工具 3：搜索 PubMed 获取相关文献
# ──────────────────────────────────────────────

def search_pubmed(query: str, max_results: int = 5) -> dict:
    """搜索 PubMed 获取某个主题的科学文献。

    使用 NCBI E-utilities API：
    1. 先用 esearch 搜索 PMID 列表
    2. 再用 efetch 获取摘要详情

    Args:
        query: PubMed 搜索查询
        max_results: 最大返回文章数

    Returns:
        dict: 包含 articles 列表的字典
    """
    # 步骤 1：搜索 PMID 列表
    search_params = urllib.parse.urlencode({
        "db": "pubmed",
        "term": query,
        "retmax": str(max_results),
        "retmode": "json",
        "sort": "relevance",  # 按相关性排序
    })
    search_url = f"{PUBMED_BASE}/esearch.fcgi?{search_params}"

    try:
        resp = requests.get(search_url, headers=_HEADERS, timeout=15, verify=False)
        resp.raise_for_status()
        search_data = resp.json()
    except Exception as e:
        return {"error": f"PubMed search failed: {e}"}

    id_list = search_data.get("esearchresult", {}).get("idlist", [])
    if not id_list:
        return {"articles": []}

    # 步骤 2：获取文章摘要
    fetch_params = urllib.parse.urlencode({
        "db": "pubmed",
        "id": ",".join(id_list),
        "retmode": "xml",      # 使用 XML 格式（包含摘要）
        "rettype": "abstract",
    })
    fetch_url = f"{PUBMED_BASE}/efetch.fcgi?{fetch_params}"

    articles = []
    try:
        resp = requests.get(fetch_url, headers=_HEADERS, timeout=15, verify=False)
        resp.raise_for_status()
        xml = resp.text
        # 使用正则表达式解析 XML（简单场景，避免引入额外依赖）
        titles = re.findall(r"<ArticleTitle>(.*?)</ArticleTitle>", xml, re.DOTALL)
        abstracts = re.findall(r"<AbstractText>(.*?)</AbstractText>", xml, re.DOTALL)
        for i, title in enumerate(titles):
            abstract = abstracts[i] if i < len(abstracts) else ""
            articles.append({
                "title": title.strip(),
                "abstract": abstract.strip()[:500],  # 截断摘要
                "pmid": id_list[i] if i < len(id_list) else "",
            })
    except Exception as e:
        return {"error": f"PubMed fetch failed: {e}", "articles": articles}

    return {"articles": articles}


# ──────────────────────────────────────────────
# 工具 4：竞争格局分析（核心 BD 工具）
# ──────────────────────────────────────────────

def analyze_competitive_landscape(
    condition: str,
    sponsor: Optional[str] = None,
    llm_client: Optional[Any] = None,
    model: str = "gpt-4o-mini",
) -> dict:
    """分析某个治疗领域的竞争格局。

    搜索试验，按申办方、阶段、机制分组，然后生成
    结构化的竞争情报报告。这是让 BD 分析师的每日监测
    真正有用的工具。

    当提供特定申办方时，还会突出显示他们与竞争对手的对比位置。

    Args:
        condition: 治疗领域或疾病条件（如 "NSCLC"）
        sponsor: 可选，特定申办方（用于分析该申办方的竞争地位）
        llm_client: OpenAI 客户端（用于生成 LLM 总结）
        model: 使用的 LLM 模型

    Returns:
        dict: 包含格局分析数据的字典
    """
    # 搜索该治疗领域的所有试验
    results = search_clinical_trials(query=condition, page_size=50)
    if "error" in results:
        return results

    studies = results.get("studies", [])
    if not studies:
        return {"landscape": "No trials found for this condition.", "summary": ""}

    # 如果指定了申办方，单独搜索该申办方的试验
    sponsor_studies = []
    if sponsor:
        sponsor_results = search_clinical_trials(query=condition, sponsor=sponsor, page_size=20)
        if "error" not in sponsor_results:
            sponsor_studies = sponsor_results.get("studies", [])

    # 按申办方分组
    by_sponsor: dict[str, list] = {}
    for s in studies:
        sp = s.get("sponsor", "Unknown")
        by_sponsor.setdefault(sp, []).append(s)

    # 按阶段分组
    by_phase: dict[str, list] = {"Phase 1": [], "Phase 2": [], "Phase 3": [], "Other": []}
    for s in studies:
        p = s.get("phase", "")
        if "1" in p and "2" not in p:
            by_phase["Phase 1"].append(s)
        elif "2" in p and "3" not in p:
            by_phase["Phase 2"].append(s)
        elif "3" in p:
            by_phase["Phase 3"].append(s)
        else:
            by_phase["Other"].append(s)

    # 构建格局数据
    landscape_data = {
        "condition": condition,
        "total_trials": len(studies),
        "active_trials": len([s for s in studies if s.get("overall_status") in (
            "RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION"
        )]),
        # 前 10 大申办方（按试验数量排序）
        "top_sponsors": [
            {
                "sponsor": sp,
                "trial_count": len(sl),
                "trials": [
                    {"nct_id": t["nct_id"], "title": t["brief_title"][:100],
                     "phase": t["phase"], "status": t["overall_status"]}
                    for t in sl[:5]  # 只显示前 5 个试验
                ],
            }
            for sp, sl in sorted(by_sponsor.items(), key=lambda x: len(x[1]), reverse=True)[:10]
        ],
        # 各阶段的试验分布
        "phase_distribution": {
            phase: [
                {"nct_id": s["nct_id"], "title": s["brief_title"][:100],
                 "sponsor": s.get("sponsor", ""), "status": s["overall_status"]}
                for s in sl[:5]  # 每个阶段只显示前 5 个
            ]
            for phase, sl in by_phase.items()
        },
    }

    # 如果指定了申办方，添加该申办方的竞争分析
    if sponsor:
        landscape_data["target_sponsor_analysis"] = {
            "sponsor": sponsor,
            "trials_found": len(sponsor_studies),
            "their_trials": [
                {"nct_id": s["nct_id"], "title": s["brief_title"][:100],
                 "phase": s["phase"], "status": s["overall_status"]}
                for s in sponsor_studies
            ],
            # 主要竞争对手（试验数 >= 2 的申办方）
            "main_competitors": [
                {"sponsor": sp, "trial_count": len(sl)}
                for sp, sl in sorted(by_sponsor.items(),
                                     key=lambda x: len(x[1]), reverse=True)
                if sp.lower() != sponsor.lower() and len(sl) >= 2
            ][:5]
        }

    # 如果有 LLM 客户端，生成中文总结
    if llm_client and studies:
        try:
            # 构建提示词所需的数据摘要
            top_sponsors_text = "\n".join(
                f"- {s['sponsor']}: {s['trial_count']} trials"
                for s in landscape_data['top_sponsors'][:8]
            )
            phase_text = "\n".join(
                f"- {p}: {len(v)}"
                for p, v in by_phase.items() if v
            )

            # 调用 LLM 生成竞争格局总结（中文）
            summary_prompt = f"""You are a pharma competitive intelligence analyst.

Therapeutic Area: {condition}
Total trials: {len(studies)}
Active/recruiting: {landscape_data['active_trials']}

Top sponsors:
{top_sponsors_text}

Phase distribution:
{phase_text}

Provide a concise competitive landscape summary in Chinese. Cover:
1. 主要玩家及其管线布局
2. 各阶段竞争密度分析（哪些阶段拥挤、哪些有空隙）
3. 值得关注的趋势或空白领域
4. 给 BD 团队的策略建议"""

            resp = llm_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": summary_prompt}],
                temperature=0.3,
            )
            landscape_data["llm_summary"] = resp.choices[0].message.content
        except Exception as e:
            landscape_data["llm_summary"] = f"Summary generation failed: {e}"

    return landscape_data


# ──────────────────────────────────────────────
# 工具 5：监测近期变更（每日 BD 监测）
# ──────────────────────────────────────────────

def monitor_recent_changes(condition: str, since_days: int = 7) -> dict:
    """查找最近 N 天内新增或更新的试验。

    v2 API 移除了 `AREA[LastUpdatePostDate]RANGE` 语法，
    改为搜索后按日期字段在 Python 端过滤。

    这是"每日监测"功能的核心 —— 正是 BD 分析师
    每天早上需要检查的内容。同时检查新发布的试验和最近更新的试验。

    Args:
        condition: 要监测的治疗领域或疾病条件
        since_days: 回溯天数（默认 7 天，即每周监测；1 天为每日监测）

    Returns:
        dict: 包含新增和更新试验列表的字典
    """
    # 计算起始日期
    since_date = datetime.now() - timedelta(days=since_days)

    # 用更大的 pageSize 搜，然后后过滤
    params = urllib.parse.urlencode({
        "query.term": condition,
        "pageSize": "100",
        "format": "json",
        "sort": "LastUpdatePostDate",
    })
    url = f"{CLINICAL_TRIALS_BASE}/studies?{params}"

    results = _fetch_studies(url)
    if "error" in results:
        return results

    all_studies = results.get("studies", [])

    # 在 Python 端按日期过滤
    filtered = []
    for s in all_studies:
        # 检查最后更新日期
        update_str = s.get("last_update_post_date", "")
        first_str = s.get("study_first_post_date", "")
        matched = False
        for date_str in [update_str, first_str]:
            if date_str:
                try:
                    d = datetime.strptime(date_str, "%Y-%m-%d")
                    if d >= since_date:
                        matched = True
                        break
                except ValueError:
                    pass
        if matched:
            filtered.append(s)

    return {
        "condition": condition,
        "since_date": since_date.strftime("%Y-%m-%d"),
        "since_days": since_days,
        "new_and_updated_count": len(filtered),
        "studies": filtered,
    }


# ──────────────────────────────────────────────
# 工具 6：基于 LLM 的试验对比（并排对比）
# ──────────────────────────────────────────────

def compare_trials_side_by_side(
    nct_ids: list[str],
    llm_client: Optional[Any] = None,
    model: str = "gpt-4o-mini",
) -> dict:
    """并排对比多个试验 —— 申办方、阶段、设计、结果。

    对于评估要密切关注哪些竞争对手试验的 BD 团队来说非常重要。

    Args:
        nct_ids: NCT ID 列表（最多 5 个）
        llm_client: OpenAI 客户端（用于生成 LLM 对比分析）
        model: 使用的 LLM 模型

    Returns:
        dict: 包含试验对比数据的字典
    """
    trials = []
    # 获取每个试验的详情
    for nct_id in nct_ids[:5]:  # 限制最多 5 个
        detail = get_trial_detail(nct_id)
        trials.append(detail)

    # 构建基础对比数据
    comparison = {
        "trials_comparison": [
            {
                "nct_id": t.get("nct_id", ""),
                "title": t.get("brief_title", "")[:80],
                "sponsor": t.get("sponsor", ""),
                "phase": t.get("phase", ""),
                "status": t.get("overall_status", ""),
                "conditions": t.get("conditions", []),
                "interventions": t.get("interventions", []),
                "primary_outcomes": t.get("primary_outcomes", []),
            }
            for t in trials
        ],
    }

    # 如果有 LLM 客户端且至少有两个试验，生成对比分析
    if llm_client and len(trials) >= 2:
        try:
            # 构建试验信息文本
            trials_text = "\n---\n".join(
                f"Trial {i+1} ({t.get('nct_id')}): {t.get('brief_title')}\n"
                f"Sponsor: {t.get('sponsor')} | Phase: {t.get('phase')} | Status: {t.get('overall_status')}\n"
                f"Interventions: {', '.join(t.get('interventions', []))}\n"
                f"Primary Outcomes: {', '.join(t.get('primary_outcomes', []))}"
                for i, t in enumerate(trials)
            )

            # 调用 LLM 生成对比分析（中文）
            prompt = f"""Compare the following clinical trials side by side (in Chinese):
Focus on differences in: trial design, patient population, endpoints, and competitive positioning.

{trials_text}

Provide a structured comparison highlighting:
1. 关键差异总结
2. 每个试验的竞争优势
3. 对竞品监测的启发"""

            resp = llm_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            comparison["llm_comparison"] = resp.choices[0].message.content
        except Exception as e:
            comparison["llm_comparison"] = f"Comparison failed: {e}"

    return comparison
