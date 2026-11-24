from concurrent.futures import ThreadPoolExecutor
import json
import re
import time
import requests
from config import (
    LLM_API_KEYS,
    LLM_ENDPOINTS,
    AGENT_MODEL_ROUTING,
    DEFAULT_EVOLUTION_STATE,
)
from logger import get_logger

log = get_logger("llm_engine")
_SESSION = requests.Session()


def has_any_llm_key() -> bool:
    return any(bool(v) for v in LLM_API_KEYS.values())


def call_llm(
    agent_role: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    max_retries: int = 2,
    json_mode: bool = False,
) -> str:
    """
    通用多模型调用与自动故障转移引擎。
    根据 agent_role 自动选择主模型，若限流/报错则无缝切换到备选大模型。
    """
    route = AGENT_MODEL_ROUTING.get(
        agent_role,
        AGENT_MODEL_ROUTING.get(
            "default",
            {"provider": "glm", "model": "glm-4-flash"},
        ),
    )
    fallback_route = AGENT_MODEL_ROUTING.get(
        "fallback", {"provider": "groq", "model": "llama-3.3-70b-versatile"}
    )

    candidates = [
        (route.get("provider"), route.get("model")),
        (
            route.get("fallback_provider", fallback_route.get("provider", "groq")),
            route.get("fallback_model", fallback_route.get("model", "llama-3.3-70b-versatile")),
        ),
        ("glm", "glm-4-flash"),
        ("deepseek", "deepseek-chat"),
        ("openai", "gpt-4o-mini"),
    ]

    seen = set()
    ordered_candidates = []
    for prov, mod in candidates:
        if not prov or not mod or (prov, mod) in seen:
            continue
        seen.add((prov, mod))
        if LLM_API_KEYS.get(prov):
            ordered_candidates.append((prov, mod))

    if not ordered_candidates:
        log.warning("[%s] 未检测到任何已配置的 LLM API Key，启用本地量化兜底。", agent_role)
        return ""

    for provider, model in ordered_candidates:
        api_key = LLM_API_KEYS.get(provider)
        endpoint = LLM_ENDPOINTS.get(provider)
        if not api_key or not endpoint:
            continue

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": 1200,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        for attempt in range(max_retries):
            try:
                resp = _SESSION.post(endpoint, headers=headers, json=payload, timeout=28)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if content:
                        return content.strip()
                elif resp.status_code == 400 and json_mode and "response_format" in payload:
                    payload.pop("response_format", None)
                    continue
                elif resp.status_code == 429:
                    wait_s = 1.5 * (attempt + 1)
                    log.warning("[%s] %s/%s 触发限流(429)，%.1fs 后重试", agent_role, provider, model, wait_s)
                    time.sleep(wait_s)
                else:
                    log.warning("[%s] %s/%s 返回状态码 %s", agent_role, provider, model, resp.status_code)
                    break
            except Exception as e:
                log.warning("[%s] 调用 %s/%s 异常 (第%d次): %s", agent_role, provider, model, attempt + 1, e)
                time.sleep(1)

    return ""


def ask_ai(
    prompt: str,
    system_prompt: str = "你是一个专业的Web3加密投研分析师，请严格按要求格式输出。",
    agent_role: str = "macro_analyst",
    temperature: float = 0.3,
    role: str = None,
    json_mode: bool = False,
) -> str:
    """兼容新版与旧版参数的 AI 调用接口"""
    resolved_role = role or agent_role
    return call_llm(
        agent_role=resolved_role,
        system_prompt=system_prompt,
        user_prompt=prompt,
        temperature=temperature,
        json_mode=json_mode,
    )


def extract_json(text: str):
    """从大模型返回文本中鲁棒提取 JSON 对象或数组"""
    if not text:
        return None
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    cleaned = re.sub(r"```json\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"```\s*", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except Exception:
        pass

    for pattern in (r"(\{.*\})", r"(\[.*\])"):
        match = re.search(pattern, cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                continue
    return None


def _run_bull_bear_debate(project_summary: str) -> tuple:
    """
    V7.0 多智能体并行辩论：Bull Agent（多头进攻视角）与 Bear Agent（空头排雷视角）并行推演
    """
    if not has_any_llm_key():
        return "", ""

    bull_sys = "你是激进但严谨的链上 Alpha 多头猎手，只寻找该项目具备高赔率爆发力、早期点火与资金共识的核心理由（60字以内）。"
    bear_sys = "你是冷酷的机构级风控审计官，专门挑刺该项目的高位派发、流动性不足、假买盘或叙事证伪风险（60字以内）。"

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_bull = pool.submit(call_llm, "bull_agent", bull_sys, project_summary, 0.35, 1, False)
        f_bear = pool.submit(call_llm, "bear_agent", bear_sys, project_summary, 0.25, 1, False)
        return f_bull.result(), f_bear.result()


def multi_agent_evaluate(project_data: dict, evolution_state: dict = None, *args, **kwargs) -> tuple:
    """
    V7.0 类脑多智能体投研委员会（Bull/Bear 并行辩论 -> CIO 终审官决策）：
    返回: (ai_score, report, verified_type, verified_track, catalyst, entry_timing)
    并就地补充 position_tier / stop_loss_pct / take_profit_pct 到 project_data（兼容 6 元组返回契约）。
    """
    evo = evolution_state or DEFAULT_EVOLUTION_STATE
    guardrails = evo.get("guardrails", DEFAULT_EVOLUTION_STATE["guardrails"])
    evo_reason = evo.get("evolution_reason", DEFAULT_EVOLUTION_STATE["evolution_reason"])
    tactical_rules = evo.get("tactical_rules", DEFAULT_EVOLUTION_STATE["tactical_rules"])
    rules_text = "\n".join([f"- {r}" for r in tactical_rules])

    symbol = project_data.get("symbol", "UNKNOWN")
    name = project_data.get("name", symbol)
    chain = project_data.get("chain", "solana")
    mc_wan = float(project_data.get("mc_wan", 0.0) or 0.0)
    liq_wan = float(project_data.get("liq_wan", 0.0) or 0.0)
    vol_wan = float(project_data.get("vol_wan", 0.0) or 0.0)
    chg_1h = float(project_data.get("chg_1h", 0.0) or 0.0)
    chg_6h = float(project_data.get("chg_6h", 0.0) or 0.0)
    chg_24h = float(project_data.get("chg_24h", 0.0) or 0.0)
    buy_ratio = float(project_data.get("buy_ratio", 50.0) or 50.0)
    pool_age_h = float(project_data.get("pool_age_hours", 48.0) or 48.0)
    age_label = project_data.get("age_label", "未知")
    quant_timing = project_data.get("entry_timing", "🟢 早期启动")
    track = project_data.get("track", "Meme")
    news_context = project_data.get("news_context", "链上资金异动，无外部新闻")
    cv_score = float(project_data.get("cv_score", 65.0) or 65.0)
    cv_signals = ", ".join(project_data.get("cv_signals") or ["链上量价信号"])
    mc_fdv = float(project_data.get("mc_fdv_ratio", 0.0) or 0.0)
    commits_4w = int(project_data.get("commits_4w", 0) or 0)
    vc_hits = ", ".join(project_data.get("vc_hits") or []) or "暂无"

    project_summary = f"""标的：{name} ({symbol}) | 公链：{chain} | 初判赛道：{track}
上线时长：{pool_age_h:.1f}h ({age_label}) | 买点阶段：{quant_timing}
市值：${mc_wan:.2f}万 | 流动性：${liq_wan:.2f}万 | 24h量：${vol_wan:.2f}万 (量/市值比: {(vol_wan / max(mc_wan, 1.0)):.2f})
动量：1h {chg_1h:+.2f}% | 6h {chg_6h:+.2f}% | 24h {chg_24h:+.2f}% | 24h买盘占比：{buy_ratio:.1f}%
多维交叉验证：{cv_score:.0f}分 ({cv_signals})
基本面穿透：MC/FDV={mc_fdv:.1f}% | GitHub月提交={commits_4w}次 | VC背书={vc_hits}
外部情报：{news_context}"""

    bull_view, bear_view = _run_bull_bear_debate(project_summary)

    system_prompt = f"""你是顶级 Web3 全周期 Alpha 基金的投资总监（CIO）。
你的核心目标是：**结合多空辩论与多维交叉验证，在极早期高赔率位置或价值击球区介入，追求胜率与盈亏比的极致平衡！**

【系统第 #{evo.get('generation', 1)} 代实盘进化记忆与强制纪律】
当前实盘统计：胜率 {evo.get('win_rate_pct', 0)}% | 盈亏比 {evo.get('payoff_ratio', 1.0)} | 进化复盘：{evo_reason}
强制铁律（违反任意一条必须将 ai_score 打到 55 分以下直接否决）：
{rules_text}
- 风控阈值：Meme市值上限 ${guardrails.get('max_meme_mc_wan', 1500)}万，价值币市值上限 ${guardrails.get('max_narrative_mc_wan', 5000)}万，24h最大允许涨幅 +{guardrails.get('max_24h_pump_limit', 68)}%。

请严格输出 JSON 格式：
{{
  "ai_score": 0到100之间的数字,
  "verified_type": "🏛️ 叙事价值" 或 "🌪️ 高波Meme",
  "verified_track": "精准细分赛道名称",
  "entry_timing": "精准买点定性（如：🟢 刚开盘极早期点火 / 💎 价值击球区 / 💎 缩量回调企稳 / ⚠️ 高位追涨风险）",
  "catalyst": "核心上涨催化剂（28字以内）",
  "position_tier": "建议仓位（如：重仓狙击(3-5%) / 标准建仓(2-3%) / 轻仓试错(1%)）",
  "stop_loss_pct": -18.0,
  "take_profit_pct": 80.0,
  "report": "综合多空辩论的犀利投研简评：明确买点逻辑、赔率空间与止盈止损位（100字以内）"
}}"""

    debate_block = ""
    if bull_view or bear_view:
        debate_block = f"\n\n【投委会多空辩论纪要】\n- 多头观点：{bull_view or '早期量价启动'}\n- 空头质疑：{bear_view or '注意高波回撤风险'}"

    raw = call_llm("cio_judge", system_prompt, project_summary + debate_block, temperature=0.2, json_mode=True)
    parsed = extract_json(raw)

    if isinstance(parsed, dict):
        try:
            ai_score = float(parsed.get("ai_score", 70.0))
        except Exception:
            ai_score = 70.0
        verified_type = str(parsed.get("verified_type") or project_data.get("project_type", "🌪️ 高波Meme"))
        verified_type = "🏛️ 叙事价值" if ("叙事" in verified_type or "价值" in verified_type) else "🌪️ 高波Meme"

        verified_track = str(parsed.get("verified_track") or track)[:24]
        entry_timing = str(parsed.get("entry_timing") or quant_timing)[:28]
        catalyst = str(parsed.get("catalyst") or f"交叉验证{cv_score:.0f}分，买盘占比{buy_ratio:.0f}%")[:45]
        report = str(
            parsed.get("report")
            or f"上线{age_label}，市值${mc_wan:.1f}万，买盘占比{buy_ratio:.0f}%，处于{quant_timing}。"
        )
        project_data["position_tier"] = str(parsed.get("position_tier") or "标准建仓(2-3%)")[:20]
        try:
            project_data["stop_loss_pct"] = float(parsed.get("stop_loss_pct", -18.0))
            project_data["take_profit_pct"] = float(parsed.get("take_profit_pct", 80.0))
        except Exception:
            pass
        return (
            round(min(max(ai_score, 0.0), 100.0), 1),
            report,
            verified_type,
            verified_track,
            catalyst,
            entry_timing,
        )

    # 本地量化兜底评分（当所有 LLM API 不可用时保证流水线正常产出）
    fallback_score = 70.0 + (cv_score - 65.0) * 0.2
    if pool_age_h <= 48 and mc_wan <= 500 and buy_ratio >= 56:
        fallback_score += 8.0
    if chg_24h > guardrails.get("max_24h_pump_limit", 68.0):
        fallback_score -= 20.0
    fallback_score = min(max(fallback_score, 0.0), 96.0)
    fallback_type = project_data.get("project_type", "🌪️ 高波Meme")
    project_data["position_tier"] = "标准建仓(2-3%)" if fallback_score >= 78 else "轻仓试错(1%)"
    project_data["stop_loss_pct"] = -15.0 if "价值" in fallback_type else -22.0
    project_data["take_profit_pct"] = 60.0 if "价值" in fallback_type else 120.0
    fallback_catalyst = f"上线{age_label}，买盘{buy_ratio:.1f}%，交叉验证{cv_score:.0f}分"
    fallback_report = (
        f"[量化引擎直评] 市值${mc_wan:.1f}万，上线{age_label}，"
        f"1h({chg_1h:+.1f}%)/24h({chg_24h:+.1f}%)处于{quant_timing}，{cv_signals}，建议{project_data['position_tier']}。"
    )
    return (
        round(fallback_score, 1),
        fallback_report,
        fallback_type,
        track,
        fallback_catalyst,
        quant_timing,
    )
