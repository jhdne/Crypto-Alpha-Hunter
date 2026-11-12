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


def call_llm(
    agent_role: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    max_retries: int = 2,
) -> str:
    """
    通用多模型调用与自动故障转移引擎。
    根据 agent_role 自动选择主模型，若限流/报错则无缝切换到备选免费大模型。
    """
    route = AGENT_MODEL_ROUTING.get(
        agent_role,
        {
            "provider": "glm",
            "model": "glm-4-flash",
            "fallback_provider": "groq",
            "fallback_model": "llama-3.3-70b-versatile",
        },
    )

    candidates = [
        (route["provider"], route["model"]),
        (route.get("fallback_provider", "groq"), route.get("fallback_model", "llama-3.3-70b-versatile")),
        ("glm", "glm-4-flash"),
        ("deepseek", "deepseek-chat"),
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
        print(f"⚠️ [{agent_role}] 未检测到任何已配置的 LLM API Key，启用本地量化兜底。")
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

        for attempt in range(max_retries):
            try:
                resp = requests.post(endpoint, headers=headers, json=payload, timeout=28)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if content:
                        return content.strip()
                elif resp.status_code == 429:
                    time.sleep(1.5 * (attempt + 1))
                else:
                    break
            except Exception as e:
                print(f"⚠️ [{agent_role}] 调用 {provider}/{model} 异常 (第{attempt+1}次): {e}")
                time.sleep(1)

    return ""


def ask_ai(
    prompt: str,
    system_prompt: str = "你是一个专业的Web3加密投研分析师，请严格按要求格式输出。",
    agent_role: str = "macro_analyst",
    temperature: float = 0.3,
) -> str:
    """兼容简化版 AI 调用接口"""
    return call_llm(
        agent_role=agent_role,
        system_prompt=system_prompt,
        user_prompt=prompt,
        temperature=temperature,
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


def multi_agent_evaluate(project_data: dict, evolution_state: dict = None, *args, **kwargs) -> tuple:
    """
    V6.0 进化感知型多智能体投研委员会：
    将 Job3 历史实盘复盘总结的《反接盘铁律》强制注入 CIO 终审官，
    精准考核：是否处于极早期、买点是否安全（拒绝高位接盘）、市值赔率是否足够高。
    返回: (ai_score, report, verified_type, verified_track, catalyst, entry_timing)
    """
    evo = evolution_state or DEFAULT_EVOLUTION_STATE
    guardrails = evo.get("guardrails", DEFAULT_EVOLUTION_STATE["guardrails"])
    evo_reason = evo.get("evolution_reason", DEFAULT_EVOLUTION_STATE["evolution_reason"])
    tactical_rules = evo.get("tactical_rules", DEFAULT_EVOLUTION_STATE["tactical_rules"])
    rules_text = "\n".join([f"- {r}" for r in tactical_rules])

    symbol = project_data.get("symbol", "UNKNOWN")
    name = project_data.get("name", symbol)
    chain = project_data.get("chain", "solana")
    mc_wan = project_data.get("mc_wan", 0.0)
    liq_wan = project_data.get("liq_wan", 0.0)
    vol_wan = project_data.get("vol_wan", 0.0)
    chg_1h = project_data.get("chg_1h", 0.0)
    chg_6h = project_data.get("chg_6h", 0.0)
    chg_24h = project_data.get("chg_24h", 0.0)
    buy_ratio = project_data.get("buy_ratio", 50.0)
    pool_age_h = project_data.get("pool_age_hours", 48.0)
    age_label = project_data.get("age_label", "未知")
    quant_timing = project_data.get("entry_timing", "🟢 早期启动")
    track = project_data.get("track", "Meme")
    news_context = project_data.get("news_context", "链上资金异动，无外部新闻")

    system_prompt = f"""你是顶级 Web3 早期 Alpha 狙击基金的投资总监（CIO）。
我们的核心目标是：**在项目极早期、低市值、第1波刚刚点火启动或缩量回调企稳的位置介入，彻底杜绝高位接盘和大市值低赔率标的！**

【系统第 #{evo.get('generation', 1)} 代实盘进化记忆与强制纪律】
自我进化复盘结论：{evo_reason}
你必须严格执行以下铁律（违反任意一条必须将 ai_score 打到 55 分以下直接否决）：
{rules_text}
- 当前风控阈值：Meme市值上限 ${guardrails.get('max_meme_mc_wan', 1500)}万，价值币市值上限 ${guardrails.get('max_narrative_mc_wan', 5000)}万，24h最大允许涨幅 +{guardrails.get('max_24h_pump_limit', 68)}%。

请严格输出 JSON 格式（不要输出任何额外解释）：
{{
  "ai_score": 0到100之间的数字（极早期黄金买点+小市值高买盘可给78-95分；若涨幅已透支或市值偏大直接给40-58分否决）,
  "verified_type": "🏛️ 叙事价值" 或 "🌪️ 高波Meme",
  "verified_track": "精准细分赛道名称（如 AI Agent / DeSci / RWA / Solana 新币Meme 等）",
  "entry_timing": "精准买点定性（如：🟢 刚开盘极早期点火 / 🟢 底部放量首阳突破 / 💎 缩量回调企稳买点 / ⚠️ 高位追涨风险）",
  "catalyst": "核心上涨催化剂或链上聪明钱异动逻辑（28字以内）",
  "report": "犀利实战投研简评：明确指出【为何现在是早期高赔率买点】、【盘口换手与买盘强度】以及【止盈止损风控位】（90字以内）"
}}"""

    user_prompt = f"""请对以下通过初筛的链上早期候选标的进行终审：
- 代币：{name} ({symbol}) | 公链：{chain} | 初判赛道：{track}
- 池子上线时长：{pool_age_h:.1f} 小时 ({age_label}) | 量化买点初判：{quant_timing}
- 市值：${mc_wan:.2f}万 | 流动性：${liq_wan:.2f}万 | 24h成交量：${vol_wan:.2f}万 (量/市值比: {(vol_wan / max(mc_wan, 1.0)):.2f})
- 价格动量：1h涨跌幅 {chg_1h:+.2f}% | 6h涨跌幅 {chg_6h:+.2f}% | 24h涨跌幅 {chg_24h:+.2f}%
- 24h主动买盘占比：{buy_ratio:.1f}%
- 关联叙事/情报：{news_context}"""

    raw = call_llm("cio_judge", system_prompt, user_prompt, temperature=0.2)
    parsed = extract_json(raw)

    if isinstance(parsed, dict):
        try:
            ai_score = float(parsed.get("ai_score", 70.0))
        except Exception:
            ai_score = 70.0
        verified_type = str(parsed.get("verified_type") or project_data.get("project_type", "🌪️ 高波Meme"))
        if "叙事" in verified_type or "价值" in verified_type:
            verified_type = "🏛️ 叙事价值"
        else:
            verified_type = "🌪️ 高波Meme"

        verified_track = str(parsed.get("verified_track") or track)[:24]
        entry_timing = str(parsed.get("entry_timing") or quant_timing)[:28]
        catalyst = str(parsed.get("catalyst") or f"24h买盘占比{buy_ratio:.0f}%，早期资金点火")[:45]
        report = str(
            parsed.get("report")
            or f"上线{age_label}，市值仅${mc_wan:.1f}万，买盘占比{buy_ratio:.0f}%，处于{quant_timing}。"
        )
        return (
            round(min(max(ai_score, 0.0), 100.0), 1),
            report,
            verified_type,
            verified_track,
            catalyst,
            entry_timing,
        )

    # 本地量化兜底评分（当所有 LLM API 不可用时保证流水线正常产出）
    fallback_score = 72.0
    if pool_age_h <= 48 and mc_wan <= 500 and buy_ratio >= 56:
        fallback_score += 8.0
    if chg_24h > guardrails.get("max_24h_pump_limit", 68.0):
        fallback_score -= 20.0
    fallback_type = project_data.get("project_type", "🌪️ 高波Meme")
    fallback_catalyst = f"上线{age_label}，买盘占比{buy_ratio:.1f}%，量价异动"
    fallback_report = (
        f"[量化引擎直评] 市值${mc_wan:.1f}万，池子上线{age_label}，"
        f"1h({chg_1h:+.1f}%)/24h({chg_24h:+.1f}%)处于{quant_timing}，买盘占比{buy_ratio:.1f}%，赔率充足。"
    )
    return (
        round(fallback_score, 1),
        fallback_report,
        fallback_type,
        track,
        fallback_catalyst,
        quant_timing,
    )
