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
    max_tool_rounds: int = 8,
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
        "6. search_pubmed — for scientific literature context on mechanisms, drugs, or targets.\n\n"
        "Workflow:\n"
        "1. Start with search_clinical_trials (by condition or condition+sponsor).\n"
        "2. For landscape analysis, call analyze_competitive_landscape directly.\n"
        "3. For monitoring, call monitor_recent_changes.\n"
        "4. Supplement with PubMed if the user asks about scientific rationale.\n"
        "5. Synthesize findings into a clear, structured report (in Chinese if the user writes in Chinese).\n\n"
        "IMPORTANT: Your output should be structured like a BD morning briefing — concise, "
        "actionable, data-driven. Include sponsor names, trial phases, and statuses.\n\n"
        "Be thorough but concise. Always state your reasoning before calling a tool."
    )

    # 初始化消息列表（系统提示 + 用户查询）
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_query},
    ]

    tools = _build_tool_choice_list()
    trace = []

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
                    # 将结果序列化为 JSON，限制长度（避免超出上下文窗口）
                    result = json.dumps(raw_result, ensure_ascii=False)[:8000]
                except Exception as e:
                    result = json.dumps({"error": str(e)})

            # 记录调用轨迹
            trace.append({
                "turn": turn + 1,
                "tool": func_name,
                "arguments": args,
                "result_preview": result[:300],
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
