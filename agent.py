"""
Agent 控制器：使用 LLM 推理来协调工具调用。

这是一个轻量级的、非框架的 Agent。它使用 OpenAI 函数调用（function-calling）
让 LLM 决定调用哪个工具、何时调用、以及传递什么参数。
"""

import json
from typing import Any, Callable

from openai import OpenAI


# ──────────────────────────────────────────────
# 工具注册表
# ──────────────────────────────────────────────

ToolFunc = Callable[..., Any]

# 全局注册表：存储所有可用工具
# 格式: {工具名: (工具函数, 工具规格)}
REGISTRY: dict[str, tuple[ToolFunc, dict]] = {}


def register_tool(name: str, func: ToolFunc, spec: dict):
    """注册一个工具到全局注册表。
    
    Args:
        name: 工具名称，LLM 将通过此名称调用工具
        func: 工具函数的引用
        spec: 工具的 OpenAI 规格（description, parameters）
    """
    REGISTRY[name] = (func, spec)


def _build_tool_choice_list() -> list[dict]:
    """从注册表构建 OpenAI 兼容的 tools 参数。
    
    Returns:
        list[dict]: OpenAI API 所需的 tools 列表
    """
    tools = []
    for name, (func, spec) in REGISTRY.items():
        tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": spec.get("description", ""),
                "parameters": spec.get("parameters", {}),
            },
        })
    return tools


# ──────────────────────────────────────────────
# Agent 运行器
# ──────────────────────────────────────────────

def run_agent(
    user_query: str,
    client: OpenAI,
    model: str = "gpt-4o-mini",
    max_tool_rounds: int = 15,
    verbose: bool = True,
) -> dict:
    """运行 Agent 循环：LLM 决策工具 → 调用 → 反馈 → 重复。
    
    这是 Agent 的核心循环。LLM 根据用户输入和工具返回结果，
    自主决定下一步调用哪个工具，直到得出最终答案。
    
    Args:
        user_query: 用户输入的查询
        client: OpenAI 客户端实例
        model: 使用的 LLM 模型
        max_tool_rounds: 最大工具调用轮数（防止无限循环）
        verbose: 是否打印详细日志
        
    Returns:
        dict: 包含 'final_response'（最终回复）和 'trace'（调用轨迹）的字典
    """
    # 系统提示词：定义 Agent 的角色、可用工具和使用场景
    system_prompt = (
        "You are a pharma competitive intelligence analyst assistant. "
        "Your users are BD (Business Development) professionals at pharma companies "
        "who need to monitor competitor pipelines on ClinicalTrials.gov.\n\n"
        "Available TOOLS and when to use them:\n"
        "1. search_clinical_trials — default tool. Searches by condition, sponsor/company, and status. "
        "Use this when the user asks about a specific company's pipeline or a therapeutic area.\n"
        "2. get_trial_detail — when you need the full protocol for a specific NCT ID.\n"
        "3. analyze_competitive_landscape — the power tool. Takes a condition (optionally a specific "
        "sponsor), and produces a structured competitive landscape report: who's doing what, "
        "phase distribution, competitor mapping. Use this for landscape overview requests.\n"
        "4. monitor_recent_changes — for daily/weekly monitoring. Checks what's new or updated "
        "in a therapeutic area in the last N days. Use when the user asks 'what's new' or "
        "'any updates in the last week'.\n"
        "5. compare_trials_side_by_side — takes up to 5 NCT IDs and produces a side-by-side "
        "comparison. Use when the user wants to compare specific competitor trials.\n"
        "6. search_pubmed — for scientific literature context on mechanisms, drugs, or targets.\n"
        "7. search_chinese_pipeline — when the user asks about Chinese pharma companies (BeiGene, Hengrui, Innovent, etc.) or Chinese domestic pipeline data. Filters ClinicalTrials.gov for Chinese sponsors.\n"
        "8. search_cde_approvals — when the user asks about CDE (China NMPA drug review) approval status or China regulatory pipeline for a specific drug. Provides links to CDE data platform.\n\n"
        "Workflow:\n"
        "1. Start with search_clinical_trials (by condition or condition+sponsor).\n"
        "2. For landscape analysis, call analyze_competitive_landscape directly.\n"
        "3. For monitoring, call monitor_recent_changes.\n"
        "4. Supplement with PubMed if the user asks about scientific rationale.\n"
        "5. Synthesize findings into a clear, structured report (in Chinese if the user writes in Chinese).\n\n"
        "IMPORTANT: Your output should be structured like a BD morning briefing — concise, "
        "actionable, data-driven. Include sponsor names, trial phases, and statuses.\n\n"
        "Be thorough but concise. Always state your reasoning before calling a tool.\n\n"
        "OUTPUT FORMAT:\n"
        "- When listing trials, include NCT links like https://clinicaltrials.gov/study/NCT04267848\n"
        "- Use markdown tables for structured data (sponsor comparison, phase distribution)\n"
        "- Highlight risky events with \u26a0\ufe0f (terminated trials, failed phases, safety concerns)\n"
        "- End with a brief 'BD Strategy Note' section when applicable\n"
        "- Output in Chinese unless the user writes in English"
    )

    # 初始化消息列表（系统提示 + 用户查询）
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_query},
    ]

    tools = _build_tool_choice_list()
    trace = []
    consecutive_errors = 0  # 连续错误计数器，防止工具全挂时死循环

    # Agent 主循环：最多执行 max_tool_rounds 轮
    for turn in range(max_tool_rounds):
        if verbose:
            print(f"\n{'='*60}\n[Agent turn {turn+1}]\n{'='*60}")

        # 调用 LLM（带工具定义）
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools if tools else None,
            tool_choice="auto" if tools else None,  # 让 LLM 自主决定是否调用工具
            temperature=0.2,  # 低温度，保证输出稳定性
        )
        msg = resp.choices[0].message

        # 打印日志
        if verbose:
            if msg.content:
                print(f"[LLM]: {msg.content[:300]}...")
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    print(f"[Tool call]: {tc.function.name}({tc.function.arguments[:200]})")

        # 将 LLM 的回复添加到消息列表
        messages.append(msg)

        # 如果 LLM 没有调用工具，说明已经得出最终答案
        if not msg.tool_calls:
            return {
                "final_response": msg.content or "",
                "trace": trace,
            }

        # 处理 LLM 请求的工具调用
        for tc in msg.tool_calls:
            func_name = tc.function.name
            
            # 检查工具是否存在
            if func_name not in REGISTRY:
                result = json.dumps({"error": f"Unknown tool: {func_name}"})
            else:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                # -- 参数清洗：LLM 有时会在参数值中混入换行、思考标签、多余空格 --
                for key, val in args.items():
                    if isinstance(val, str):
                        val = val.replace("<thinking>", "").replace("</thinking>", "")
                        val = " ".join(val.split())
                        args[key] = val.strip()
                    elif isinstance(val, list):
                        cleaned = []
                        for item in val:
                            if isinstance(item, str):
                                item = item.replace("<thinking>", "").replace("</thinking>", "")
                                item = " ".join(item.split()).strip()
                            cleaned.append(item)
                        args[key] = cleaned

                func, spec = REGISTRY[func_name]
                
                # 为需要 LLM 客户端的工具注入 client
                # （用于调用 LLM 进行分析和总结）
                if func_name in ("analyze_eligibility", "analyze_competitive_landscape",
                                 "compare_trials_side_by_side"):
                    args["llm_client"] = client

                if verbose:
                    print(f"  → Calling: {func_name}({args})")

                # 执行工具函数
                try:
                    raw_result = func(**args)
                    # 检查工具是否返回了错误
                    if isinstance(raw_result, dict) and "error" in raw_result:
                        result = json.dumps(raw_result, ensure_ascii=False)[:8000]
                        consecutive_errors += 1
                    else:
                        # 将结果序列化为 JSON，限制长度（避免超出上下文窗口）
                        result = json.dumps(raw_result, ensure_ascii=False)[:8000]
                        consecutive_errors = 0  # 成功，重置计数器
                except Exception as e:
                    error_msg = str(e)
                    if "401" in error_msg or "Unauthorized" in error_msg or "Authentication" in error_msg:
                        friendly = "[凭证错误] API Key 无效或已过期，请在侧边栏检查 API Key 配置"
                    elif "429" in error_msg or "Rate limit" in error_msg:
                        friendly = "[限流] API 请求过于频繁，请稍后重试"
                    elif "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                        friendly = "[超时] 接口请求超时，可能是网络环境不稳定，请重试"
                    else:
                        friendly = f"[工具调用失败] {error_msg[:200]}"
                    result = json.dumps({"error": friendly})
                    consecutive_errors += 1

            # 连续 3 次工具调用都失败 → 提前终止，避免空转
            if consecutive_errors >= 3:
                messages.append({
                    "role": "user",
                    "content": "[System note: Multiple tool calls failed. Please provide your best response based on available information.]",
                })
                # 再给 LLM 一次机会生成最终回复（不带工具）
                final_resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.2,
                )
                return {
                    "final_response": final_resp.choices[0].message.content or "All API calls failed. Unable to complete the analysis.",
                    "trace": trace,
                }

            # 记录调用轨迹
            # 剔除不可序列化的对象（如 llm_client），避免 json.dumps 报错
            trace_args = {k: v for k, v in args.items() if k != "llm_client"}
            trace.append({
                "turn": turn + 1,
                "tool": func_name,
                "arguments": trace_args,
                "result_preview": result[:500],  # trace 展示用截断版
                "_full_result": result,  # 完整结果，供前端渲染图表/表格
            })

            # 将工具执行结果添加到消息列表（供 LLM 下一轮使用）
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    # 如果达到最大轮数仍未完成，返回提示信息
    return {
        "final_response": "Agent reached maximum tool call rounds.",
        "trace": trace,
    }


# ──────────────────────────────────────────────
# Agent 运行器（流式版）
# ──────────────────────────────────────────────

def run_agent_stream(
    user_query: str,
    client: OpenAI,
    model: str = "gpt-4o-mini",
    max_tool_rounds: int = 15,
    verbose: bool = True,
):
    """流式版 Agent 循环：边推理边把文本 / 工具调用作为事件 yield 出去。

    与 ``run_agent`` 的区别：不再等全部结束才返回，而是把中间过程
    实时推送出来（适合 Streamlit 等需要「打字机」效果的前端）。

    Yields dict events:
        {"type": "content", "text": str}                 # 流式文本片段（推理或最终回答）
        {"type": "tool_start", "tool": str, "args": dict}  # 开始调用工具
        {"type": "tool_done", "tool": str, "preview": str} # 工具返回（截断预览）
        {"type": "final", "text": str, "trace": list}    # 正常结束，附完整轨迹
        {"type": "error", "text": str}                   # 致命错误（如凭证问题）
    """
    system_prompt = (
        "You are a pharma competitive intelligence analyst assistant. "
        "Your users are BD (Business Development) professionals at pharma companies "
        "who need to monitor competitor pipelines on ClinicalTrials.gov.\n\n"
        "Available TOOLS and when to use them:\n"
        "1. search_clinical_trials — default tool. Searches by condition, sponsor/company, and status. "
        "Use this when the user asks about a specific company's pipeline or a therapeutic area.\n"
        "2. get_trial_detail — when you need the full protocol for a specific NCT ID.\n"
        "3. analyze_competitive_landscape — the power tool. Takes a condition (optionally a specific "
        "sponsor), and produces a structured competitive landscape report: who's doing what, "
        "phase distribution, competitor mapping. Use this for landscape overview requests.\n"
        "4. monitor_recent_changes — for daily/weekly monitoring. Checks what's new or updated "
        "in a therapeutic area in the last N days. Use when the user asks 'what's new' or "
        "'any updates in the last week'.\n"
        "5. compare_trials_side_by_side — takes up to 5 NCT IDs and produces a side-by-side "
        "comparison. Use when the user wants to compare specific competitor trials.\n"
        "6. search_pubmed — for scientific literature context on mechanisms, drugs, or targets.\n"
        "7. search_chinese_pipeline — when the user asks about Chinese pharma companies (BeiGene, Hengrui, Innovent, etc.) or Chinese domestic pipeline data. Filters ClinicalTrials.gov for Chinese sponsors.\n"
        "8. search_cde_approvals — when the user asks about CDE (China NMPA drug review) approval status or China regulatory pipeline for a specific drug. Provides links to CDE data platform.\n\n"
        "Workflow:\n"
        "1. Start with search_clinical_trials (by condition or condition+sponsor).\n"
        "2. For landscape analysis, call analyze_competitive_landscape directly.\n"
        "3. For monitoring, call monitor_recent_changes.\n"
        "4. Supplement with PubMed if the user asks about scientific rationale.\n"
        "5. Synthesize findings into a clear, structured report (in Chinese if the user writes in Chinese).\n\n"
        "IMPORTANT: Your output should be structured like a BD morning briefing — concise, "
        "actionable, data-driven. Include sponsor names, trial phases, and statuses.\n\n"
        "Be thorough but concise. Always state your reasoning before calling a tool.\n\n"
        "OUTPUT FORMAT:\n"
        "- When listing trials, include NCT links like https://clinicaltrials.gov/study/NCT04267848\n"
        "- Use markdown tables for structured data (sponsor comparison, phase distribution)\n"
        "- Highlight risky events with ⚠️ (terminated trials, failed phases, safety concerns)\n"
        "- End with a brief 'BD Strategy Note' section when applicable\n"
        "- Output in Chinese unless the user writes in English"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_query},
    ]

    tools = _build_tool_choice_list()
    trace = []
    consecutive_errors = 0  # 连续错误计数器，防止工具全挂时死循环

    for turn in range(max_tool_rounds):
        if verbose:
            print(f"\n{'='*60}\n[Agent turn {turn+1}]\n{'='*60}")

        # ── 流式调用 LLM ──
        stream = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools if tools else None,
            tool_choice="auto" if tools else None,
            temperature=0.2,
            stream=True,  # 关键：开启流式
        )

        content_buf = ""          # 本轮累积文本
        tool_calls_buf = []        # 本轮累积工具调用 [{id, name, args_str}]
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            # 文本片段 → 实时推送
            if delta.content:
                content_buf += delta.content
                yield {"type": "content", "text": delta.content}

            # 工具调用增量（function calling 流式返回）
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index if tc.index is not None else 0
                    while len(tool_calls_buf) <= idx:
                        tool_calls_buf.append({"id": "", "name": "", "args_str": ""})
                    if tc.id:
                        tool_calls_buf[idx]["id"] += tc.id
                    if tc.function and tc.function.name:
                        tool_calls_buf[idx]["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        tool_calls_buf[idx]["args_str"] += tc.function.arguments

        # ── 构造本轮 assistant 消息（OpenAI 需要完整 tool_calls）──
        assistant_msg = {"role": "assistant", "content": content_buf or None}
        if tool_calls_buf:
            assistant_msg["tool_calls"] = [
                {"id": t["id"], "type": "function",
                 "function": {"name": t["name"], "arguments": t["args_str"]}}
                for t in tool_calls_buf if t["name"]
            ]
        messages.append(assistant_msg)

        # 没有工具调用 → 这就是最终答案，结束
        if not tool_calls_buf or all(not t["name"] for t in tool_calls_buf):
            yield {"type": "final", "text": content_buf, "trace": trace}
            return

        # ── 逐个执行工具调用 ──
        for tc in tool_calls_buf:
            if not tc["name"]:
                continue
            func_name = tc["name"]

            # 解析参数 JSON（流式可能截断，做兜底）
            try:
                args = json.loads(tc["args_str"] or "{}")
            except json.JSONDecodeError:
                args = {}

            # -- 参数清洗：LLM 有时会在参数值中混入换行、思考标签、多余空格 --
            for key, val in args.items():
                if isinstance(val, str):
                    val = val.replace("<thinking>", "").replace("</thinking>", "")
                    val = " ".join(val.split())
                    args[key] = val.strip()
                elif isinstance(val, list):
                    cleaned = []
                    for item in val:
                        if isinstance(item, str):
                            item = item.replace("<thinking>", "").replace("</thinking>", "")
                            item = " ".join(item.split()).strip()
                        cleaned.append(item)
                    args[key] = cleaned

            # 先通知前端「工具开始」（无论工具是否注册都展示，避免 UI 静默丢事件）
            yield {"type": "tool_start", "tool": func_name,
                   "args": {k: v for k, v in args.items() if k != "llm_client"}}

            if func_name not in REGISTRY:
                result = json.dumps({"error": f"Unknown tool: {func_name}"})
                consecutive_errors += 1
            else:
                func, spec = REGISTRY[func_name]
                # 为需要 LLM 客户端的工具注入 client
                if func_name in ("analyze_eligibility", "analyze_competitive_landscape",
                                 "compare_trials_side_by_side"):
                    args["llm_client"] = client

                if verbose:
                    print(f"  → Calling: {func_name}({args})")

                try:
                    raw_result = func(**args)
                    if isinstance(raw_result, dict) and "error" in raw_result:
                        result = json.dumps(raw_result, ensure_ascii=False)[:8000]
                        consecutive_errors += 1
                    else:
                        result = json.dumps(raw_result, ensure_ascii=False)[:8000]
                        consecutive_errors = 0
                except Exception as e:
                    error_msg = str(e)
                    if "401" in error_msg or "Unauthorized" in error_msg or "Authentication" in error_msg:
                        friendly = "[凭证错误] API Key 无效或已过期，请在侧边栏检查 API Key 配置"
                    elif "429" in error_msg or "Rate limit" in error_msg:
                        friendly = "[限流] API 请求过于频繁，请稍后重试"
                    elif "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                        friendly = "[超时] 接口请求超时，可能是网络环境不稳定，请重试"
                    else:
                        friendly = f"[工具调用失败] {error_msg[:200]}"
                    result = json.dumps({"error": friendly})
                    consecutive_errors += 1

            # 通知前端「工具完成」（已知/未知工具均在此抛出）
            yield {"type": "tool_done", "tool": func_name, "preview": result[:300]}

            # 连续 3 次工具调用都失败 → 提前终止
            if consecutive_errors >= 3:
                messages.append({
                    "role": "user",
                    "content": "[System note: Multiple tool calls failed. Please provide your best response based on available information.]",
                })
                # 兜底最终回复（流式输出）
                fb_stream = client.chat.completions.create(
                    model=model, messages=messages, temperature=0.2, stream=True)
                fb_text = ""
                for chunk in fb_stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        fb_text += chunk.choices[0].delta.content
                        yield {"type": "content", "text": chunk.choices[0].delta.content}
                yield {"type": "final",
                       "text": fb_text or "All API calls failed. Unable to complete the analysis.",
                       "trace": trace}
                return

            # 记录调用轨迹
            trace_args = {k: v for k, v in args.items() if k != "llm_client"}
            trace.append({
                "turn": turn + 1,
                "tool": func_name,
                "arguments": trace_args,
                "result_preview": result[:500],
                "_full_result": result,
            })

            # 将工具执行结果追加到消息列表（供 LLM 下一轮使用）
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })

    # 达到最大轮数仍未完成
    yield {"type": "final", "text": "Agent reached maximum tool call rounds.", "trace": trace}
