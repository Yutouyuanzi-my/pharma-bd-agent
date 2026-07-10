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
import time
import urllib.parse
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional, Any

import requests
import urllib3

# 屏蔽 requests 关闭验证时的控制台警告（国内网络开发用）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# API 基础 URL
CLINICAL_TRIALS_BASE = "https://clinicaltrials.gov/api/v2"
PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# 默认请求头（模拟浏览器，绕过 WAF）
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# -- 简单内存缓存 --
_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 300  # 5 分钟


def _cached_request(url: str) -> dict:
    """带缓存的 HTTP GET，相同 URL 5 分钟内不重复请求。"""
    now = time.time()
    if url in _cache:
        expire, data = _cache[url]
        if now < expire:
            return data
    # 重试 3 次，退避
    last_err = None
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=15, verify=False)
            resp.raise_for_status()
            data = resp.json()
            _cache[url] = (now + _CACHE_TTL, data)
            return data
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code
            if status == 429:
                # 限流：等 (attempt+1)*2 秒后重试
                time.sleep((attempt + 1) * 2)
                last_err = e
                continue
            elif status in (401, 403):
                # 权限/认证错误，不重试
                return {"error": f"HTTP {status}: Access denied. Check API/network settings."}
            elif status >= 500:
                # 服务端错误，重试
                time.sleep((attempt + 1) * 1)
                last_err = e
                continue
            else:
                return {"error": f"HTTP {status}: {e.response.text[:200]}"}
        except requests.exceptions.Timeout:
            last_err = "timeout"
            time.sleep((attempt + 1) * 2)
        except requests.exceptions.ConnectionError:
            last_err = "connection"
            time.sleep((attempt + 1) * 3)
        except Exception as e:
            return {"error": str(e)}
    return {"error": f"Request failed after 3 retries. Last error: {last_err}"}


def _risk_tags(study: dict) -> list[str]:
    """对试验标注风险/价值标签。"""
    tags = []
    status = (study.get("overall_status") or "").upper()
    phase = study.get("phase") or ""
    title = study.get("brief_title") or ""

    # 风险标记
    if status in ("TERMINATED", "WITHDRAWN", "SUSPENDED"):
        tags.append("⚠️ 已终止")
    if "fail" in title.lower() or "unsafe" in title.lower() or "toxicity" in title.lower():
        tags.append("⚠️ 安全性信号")
    if "phase 2" in phase.lower() and status == "COMPLETED":
        # Phase 2 完成 → 可能进入 Phase 3，值得关注
        if "phase 3" not in title.lower():
            tags.append("📈 Phase 2 完成")

    # 价值标记
    if status == "RECRUITING" and ("phase 3" in phase.lower() or "phase 2" in phase.lower()):
        tags.append("🔬 招募中")
    if "first" in title.lower() or "first-in-human" in title.lower() or "FIH" in title:
        tags.append("🧬 First-in-Human")
    if "breakthrough" in title.lower() or "priority" in title.lower():
        tags.append("🏆 突破性疗法")

    return tags


# ──────────────────────────────────────────────
# 工具 1：搜索 ClinicalTrials.gov
# ──────────────────────────────────────────────

def search_clinical_trials(
    query: str,
    sponsor: Optional[str] = None,
    status: Optional[str] = None,
    page_size: int = 10,
    format: str = "json",
) -> dict:
    """按疾病、公司/申办方、状态搜索 ClinicalTrials.gov。"""
    term_parts = [query]
    if sponsor:
        term_parts.append(sponsor)
    if status:
        term_parts.append(status.lower())
    params = {
        "query.term": " ".join(term_parts),
        "pageSize": str(min(page_size * 5, 100)),
        "format": format,
    }
    url = f"{CLINICAL_TRIALS_BASE}/studies?" + urllib.parse.urlencode(params)
    data = _cached_request(url)
    if "error" in data:
        return data

    studies = [_summarize_study(s.get("protocolSection", {})) for s in data.get("studies", [])]

    # 后过滤
    if sponsor:
        sponsor_lower = sponsor.strip().lower()
        studies = [s for s in studies if sponsor_lower in (s.get("sponsor") or "").lower()]
    if status:
        status_lower = status.strip().lower()
        studies = [s for s in studies if (s.get("overall_status") or "").lower() == status_lower]

    return {"total_count": len(studies), "studies": studies[:page_size]}


def _fetch_studies(url: str) -> dict:
    """内部函数：从 URL 获取并汇总试验列表。"""
    data = _cached_request(url)
    if "error" in data:
        return data
    studies = data.get("studies", [])
    return {
        "total_count": len(studies),
        "studies": [_summarize_study(s.get("protocolSection", {})) for s in studies],
    }


def _summarize_study(ps: dict) -> dict:
    """从 protocolSection 提取核心字段并添加衍生信息。"""
    id_mod = ps.get("identificationModule", {})
    sponsor_mod = ps.get("sponsorCollaboratorsModule", {})
    des_mod = ps.get("descriptionModule", {})
    stat_mod = ps.get("statusModule", {})
    desig_mod = ps.get("designModule", {})
    elig_mod = ps.get("eligibilityModule", {})
    cond_mod = ps.get("conditionsModule", {})
    int_mod = ps.get("interventionsModule", {})
    outcome_mod = ps.get("outcomesModule", {})

    nct_id = id_mod.get("nctId", "")
    result = {
        "nct_id": nct_id,
        "nct_link": f"https://clinicaltrials.gov/study/{nct_id}",
        "brief_title": id_mod.get("briefTitle", ""),
        "sponsor": (sponsor_mod.get("leadSponsor") or {}).get("name", ""),
        "collaborators": [c.get("name", "") for c in (sponsor_mod.get("collaborators") or [])],
        "brief_summary": (des_mod.get("briefSummary") or "")[:500],
        "overall_status": stat_mod.get("overallStatus", ""),
        "phase": desig_mod.get("phases", [None])[0] if desig_mod.get("phases") else "",
        "conditions": cond_mod.get("conditions", []),
        "interventions": [i.get("name", "") for i in (int_mod.get("interventions") or [])],
        "primary_outcomes": [o.get("measure", "") for o in (outcome_mod.get("primaryOutcomes") or [])],
        "eligibility_criteria": (elig_mod.get("eligibilityCriteria") or "")[:2000],
        "sex": elig_mod.get("sex", ""),
        "minimum_age": elig_mod.get("minimumAge", ""),
        "maximum_age": elig_mod.get("maximumAge", ""),
        "healthy_volunteers": elig_mod.get("healthyVolunteers", ""),
        "last_update_post_date": (stat_mod.get("lastUpdatePostDateStruct") or {}).get("date", ""),
        "study_first_post_date": (stat_mod.get("studyFirstPostDateStruct") or {}).get("date", ""),
    }
    # 附加风险/价值标签
    result["risk_tags"] = _risk_tags(result)
    return result


# ──────────────────────────────────────────────
# 工具 2：根据 NCT ID 获取单个试验的完整协议
# ──────────────────────────────────────────────

def get_trial_detail(nct_id: str) -> dict:
    """根据 NCT ID 获取单个试验的完整协议。"""
    url = f"{CLINICAL_TRIALS_BASE}/studies/{nct_id}?format=json"
    data = _cached_request(url)
    if "error" in data:
        return data
    ps = data.get("protocolSection", {})
    return _summarize_study(ps)


# ──────────────────────────────────────────────
# 工具 3：搜索 PubMed 获取相关文献
# ──────────────────────────────────────────────

def search_pubmed(query: str, max_results: int = 5) -> dict:
    """搜索 PubMed 获取某个主题的科学文献。"""
    search_params = urllib.parse.urlencode({
        "db": "pubmed", "term": query,
        "retmax": str(max_results), "retmode": "json", "sort": "relevance",
    })
    search_url = f"{PUBMED_BASE}/esearch.fcgi?{search_params}"
    search_data = _cached_request(search_url)
    if "error" in search_data:
        # 不要缓存失败的 PubMed 请求，直接尝试请求
        try:
            resp = requests.get(search_url, headers=_HEADERS, timeout=15, verify=False)
            resp.raise_for_status()
            search_data = resp.json()
        except Exception as e:
            return {"error": f"PubMed search failed: {e}"}

    id_list = search_data.get("esearchresult", {}).get("idlist", [])
    if not id_list:
        return {"articles": []}

    fetch_params = urllib.parse.urlencode({
        "db": "pubmed", "id": ",".join(id_list),
        "retmode": "xml", "rettype": "abstract",
    })
    fetch_url = f"{PUBMED_BASE}/efetch.fcgi?{fetch_params}"
    articles = []
    try:
        resp = requests.get(fetch_url, headers=_HEADERS, timeout=15, verify=False)
        resp.raise_for_status()
        xml = resp.text
        titles = re.findall(r"<ArticleTitle>(.*?)</ArticleTitle>", xml, re.DOTALL)
        abstracts = re.findall(r"<AbstractText>(.*?)</AbstractText>", xml, re.DOTALL)
        for i, title in enumerate(titles):
            pmid = id_list[i] if i < len(id_list) else ""
            abstract = abstracts[i] if i < len(abstracts) else ""
            articles.append({
                "title": title.strip(),
                "abstract": abstract.strip()[:500],
                "pmid": pmid,
                "pubmed_link": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
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
    """分析某个治疗领域的竞争格局。"""
    results = search_clinical_trials(query=condition, page_size=50)
    if "error" in results:
        return results
    studies = results.get("studies", [])
    if not studies:
        return {"landscape": "No trials found for this condition.", "summary": ""}

    sponsor_studies = []
    if sponsor:
        sponsor_results = search_clinical_trials(query=condition, sponsor=sponsor, page_size=20)
        if "error" not in sponsor_results:
            sponsor_studies = sponsor_results.get("studies", [])

    by_sponsor: dict[str, list] = {}
    for s in studies:
        sp = s.get("sponsor", "Unknown")
        by_sponsor.setdefault(sp, []).append(s)

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

    landscape_data = {
        "condition": condition,
        "total_trials": len(studies),
        "active_trials": len([s for s in studies if s.get("overall_status") in (
            "RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION")]),
        "top_sponsors": [{
            "sponsor": sp, "trial_count": len(sl),
            "trials": [{"nct_id": t["nct_id"], "nct_link": t.get("nct_link", ""),
                        "title": t["brief_title"][:100], "phase": t["phase"],
                        "status": t["overall_status"], "risk_tags": t.get("risk_tags", [])}
                       for t in sl[:5]],
        } for sp, sl in sorted(by_sponsor.items(), key=lambda x: len(x[1]), reverse=True)[:10]],
        "phase_distribution": {phase: [{"nct_id": s["nct_id"], "title": s["brief_title"][:100],
                                         "sponsor": s.get("sponsor", ""), "status": s["overall_status"]}
                                        for s in sl[:5]] for phase, sl in by_phase.items()},
    }

    if sponsor:
        landscape_data["target_sponsor_analysis"] = {
            "sponsor": sponsor,
            "trials_found": len(sponsor_studies),
            "their_trials": [{"nct_id": s["nct_id"], "title": s["brief_title"][:100],
                              "phase": s["phase"], "status": s["overall_status"]}
                             for s in sponsor_studies],
            "main_competitors": [{"sponsor": sp, "trial_count": len(sl)}
                                 for sp, sl in sorted(by_sponsor.items(),
                                     key=lambda x: len(x[1]), reverse=True)
                                 if sp.lower() != sponsor.lower() and len(sl) >= 2][:5],
        }

    if llm_client and studies:
        try:
            top_sponsors_text = "\n".join(
                f"- {s['sponsor']}: {s['trial_count']} trials" for s in landscape_data['top_sponsors'][:8])
            phase_text = "\n".join(f"- {p}: {len(v)}" for p, v in by_phase.items() if v)
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
                model=model, messages=[{"role": "user", "content": summary_prompt}], temperature=0.3)
            landscape_data["llm_summary"] = resp.choices[0].message.content
        except Exception as e:
            landscape_data["llm_summary"] = f"Summary generation failed: {e}"
    return landscape_data


# ──────────────────────────────────────────────
# 工具 5：监测近期变更（每日 BD 监测）
# ──────────────────────────────────────────────

def monitor_recent_changes(condition: str, since_days: int = 7) -> dict:
    """查找最近 N 天内新增或更新的试验。"""
    since_date = datetime.now() - timedelta(days=since_days)
    params = urllib.parse.urlencode({
        "query.term": condition, "pageSize": "100",
        "format": "json", "sort": "LastUpdatePostDate",
    })
    url = f"{CLINICAL_TRIALS_BASE}/studies?{params}"
    results = _fetch_studies(url)
    if "error" in results:
        return results

    all_studies = results.get("studies", [])
    filtered = []
    for s in all_studies:
        for date_str in [s.get("last_update_post_date", ""), s.get("study_first_post_date", "")]:
            if date_str:
                try:
                    d = datetime.strptime(date_str, "%Y-%m-%d")
                    if d >= since_date:
                        filtered.append(s)
                        break
                except ValueError:
                    pass

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
    """并排对比多个试验。"""
    trials = []
    for nct_id in nct_ids[:5]:
        detail = get_trial_detail(nct_id)
        trials.append(detail)

    comparison = {
        "trials_comparison": [{
            "nct_id": t.get("nct_id", ""),
            "nct_link": t.get("nct_link", ""),
            "title": t.get("brief_title", "")[:80],
            "sponsor": t.get("sponsor", ""),
            "phase": t.get("phase", ""),
            "status": t.get("overall_status", ""),
            "conditions": t.get("conditions", []),
            "interventions": t.get("interventions", []),
            "primary_outcomes": t.get("primary_outcomes", []),
            "risk_tags": t.get("risk_tags", []),
        } for t in trials],
    }

    if llm_client and len(trials) >= 2:
        try:
            trials_text = "\n---\n".join(
                f"Trial {i+1} ({t.get('nct_id')}): {t.get('brief_title')}\n"
                f"Sponsor: {t.get('sponsor')} | Phase: {t.get('phase')} | Status: {t.get('overall_status')}\n"
                f"Interventions: {', '.join(t.get('interventions', []))}\n"
                f"Primary Outcomes: {', '.join(t.get('primary_outcomes', []))}"
                for i, t in enumerate(trials))
            prompt = f"""Compare the following clinical trials side by side (in Chinese):
Focus on differences in: trial design, patient population, endpoints, and competitive positioning.

{trials_text}

Provide a structured comparison highlighting:
1. 关键差异总结
2. 每个试验的竞争优势
3. 对竞品监测的启发"""
            resp = llm_client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": prompt}], temperature=0.2)
            comparison["llm_comparison"] = resp.choices[0].message.content
        except Exception as e:
            comparison["llm_comparison"] = f"Comparison failed: {e}"
    return comparison


# ============================================================
# 工具 7：中国药企管线搜索（基于 ClinicalTrials.gov + 中国药企名过滤）
# ============================================================

# 常见中国药企名称模式（用于识别 ClinicalTrials.gov 中的中国申办方）
_CHINESE_SPONSOR_PATTERNS = [
    "百济神州", "BeiGene",
    "君实生物", "Junshi",
    "信达生物", "Innovent",
    "恒瑞医药", "Hengrui",
    "石药集团", "CSPC",
    "中国生物制药", "Sino Biopharm",
    "复星医药", "Fosun",
    "科伦药业", "Kelun",
    "齐鲁制药", "Qilu",
    "正大天晴", "CTTQ",
    "诺诚健华", "InnoCare",
    "康方生物", "Akeso",
    "荣昌生物", "RemeGen",
    "再鼎医药", "Zai Lab",
    "和黄医药", "Hutchison", "Hutchmed",
    "康宁杰瑞", "Alphamab",
    "亚盛医药", "Ascentage",
    "德琪医药", "Antengene",
    "加科思", "Jacobio",
    "科济药业", "CARsgen",
    "百奥泰", "Bio-Thera",
    "神州细胞", "Sinocelltech",
    "腾盛博药", "Brii Biosciences",
    "天境生物", "TJ Biologics", "I-Mab",
    "传奇生物", "Legend Biotech",
    "药明", "WuXi",
]


def search_chinese_pipeline(
    condition: str,
    sponsor: Optional[str] = None,
    page_size: int = 10,
) -> dict:
    """搜索中国药企在 ClinicalTrials.gov 上的临床试验管线。

    通过中文药企名模式自动识别中国申办方，适合 BD 追踪国内药企管线。

    Args:
        condition: 治疗领域或疾病条件（如 "NSCLC", "PD-1"）
        sponsor: 可选，指定某家中国药企名称
        page_size: 返回结果数量

    Returns:
        dict: 包含中国药企管线数据的字典
    """
    # 用条件搜索 ClinicalTrials.gov
    params = {
        "query.term": condition,
        "pageSize": str(min(page_size * 5, 100)),
        "format": "json",
    }
    import urllib.parse
    url = f"{CLINICAL_TRIALS_BASE}/studies?" + urllib.parse.urlencode(params)
    data = _cached_request(url)
    if "error" in data:
        return data

    studies = [_summarize_study(s.get("protocolSection", {})) for s in data.get("studies", [])]

    # 按中国药企名模式过滤
    if sponsor:
        sponsor_lower = sponsor.strip().lower()
        matched = [
            s for s in studies
            if sponsor_lower in (s.get("sponsor") or "").lower()
        ]
    else:
        matched = []
        for s in studies:
            sp = (s.get("sponsor") or "").lower()
            for pattern in _CHINESE_SPONSOR_PATTERNS:
                if pattern.lower() in sp:
                    matched.append(s)
                    break

    # 按申办方分组
    by_sponsor: dict[str, list] = {}
    for s in matched:
        sp = s.get("sponsor", "Unknown")
        by_sponsor.setdefault(sp, []).append(s)

    top = sorted(by_sponsor.items(), key=lambda x: len(x[1]), reverse=True)

    return {
        "condition": condition,
        "total_chinese_trials": len(matched),
        "chinese_sponsors": [
            {"sponsor": sp, "trial_count": len(sl),
             "trials": [{"nct_id": t["nct_id"], "nct_link": t.get("nct_link", ""),
                         "title": t["brief_title"][:100], "phase": t["phase"],
                         "status": t["overall_status"], "risk_tags": t.get("risk_tags", [])}
                        for t in sl[:5]]}
            for sp, sl in top[:10]
        ],
        # 搜索 ChiCTR 的快捷链接
        "chictr_search_link": f"http://www.chictr.org.cn/searchproj.html?key={urllib.parse.quote(condition)}",
        "note": "以上数据来自 ClinicalTrials.gov（中国药企全球注册）。国内 ChiCTR 数据请点击上方链接直达搜索页。",
    }


# ============================================================
# 工具 8：CDE 药品审批进度查询
# ============================================================

# 已知 CDE 关键审批节点关键词
_CDE_MILESTONES = [
    ("IND 受理", "IND受理/临床试验申请"),
    ("IND 批件", "临床试验批件"),
    ("NDA 受理", "NDA受理/上市申请"),
    ("NDA 批件", "NDA批件/上市批准"),
    ("优先审评", "优先审评"),
    ("突破性疗法", "突破性疗法认定"),
]

def search_cde_approvals(
    drug_name: str,
    milestone: Optional[str] = None,
) -> dict:
    """查询 CDE（中国药品审评中心）药品审评进度。

    注意：CDE 官网暂未提供公开 JSON API，此工具提供：
    1. 直达 CDE 数据查询页的快捷链接
    2. 已知审评进度关键词参考
    3. 同药品在 ClinicalTrials.gov 上的中国试验概况

    Args:
        drug_name: 药品名称（通用名或商品名，如 "替雷利珠单抗"、"tislelizumab"）
        milestone: 可选，审评阶段关键词（如 "IND受理"、"NDA批件"）

    Returns:
        dict: 包含 CDE 查询信息和关联数据的字典
    """
    import urllib.parse

    result = {
        "drug_name": drug_name,
        "cde_search_link": (
            f"https://www.cde.org.cn/search?keyword={urllib.parse.quote(drug_name)}"
        ),
        "clinical_trial_link": (
            f"http://www.chinadrugtrials.org.cn/clinicaltrials.search.list"
            f"?condition={urllib.parse.quote(drug_name)}"
        ),
        "cde_milestones": _CDE_MILESTONES,
        "quick_links": {
            "CDE 数据查询": "https://www.cde.org.cn/platform/query",
            "药物临床试验登记平台": "http://www.chinadrugtrials.org.cn/",
            "CDE 优先审评公示": "https://www.cde.org.cn/priority",
        },
    }

    # 同时在 ClinicalTrials.gov 搜索该药品的中国试验
    try:
        ct_results = search_clinical_trials(query=drug_name, page_size=5)
        if "error" not in ct_results:
            studies = ct_results.get("studies", [])
            # 筛选中国药企
            chinese = []
            for s in studies:
                sp = (s.get("sponsor") or "").lower()
                for pat in _CHINESE_SPONSOR_PATTERNS:
                    if pat.lower() in sp:
                        chinese.append(s)
                        break
            result["related_chinese_trials"] = chinese[:5] if chinese else studies[:3]
    except Exception:
        pass

    return result
