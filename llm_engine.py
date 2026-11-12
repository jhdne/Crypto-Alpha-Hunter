# llm_engine.py - V6.0 具备进化记忆注入与买点位置审计的多智能体引擎
import json
import re
import time
import requests
from config import LLM_API_KEYS, LLM_ENDPOINTS, AGENT_MODEL_ROUTING, DEFAULT_EVOLUTION_STATE

_GROQ_LIVE_MODELS_CACHE = None


def _get_groq_live_models(api_key):
    global _GROQ_LIVE_MODELS_CACHE
    if _GROQ_LIVE_MODELS_CACHE:
        return _GROQ_LIVE_MODELS_CACHE
    try:
        resp = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            models = [
                m["id"]
                for m in data
                if "whisper" not in m["id"].lower()
                and "tts" not in m["id"].lower()
                and "guard" not in m["id"].lower()
                and "vision" not in m["id"].lower()
            ]
            preferred = [
                "llama-3.3-70b-versatile",
                "llama-3.1-8b-instant",
                "deepseek-r1-distill-llama-70b",
                "qwen-qwq-32b",
                "llama3-70b-8192",
                "llama3-8b-8192",
            ]
            ordered = [m for m in preferred if m in models] + [
                m for m in models if m not in preferred
            ]
            if ordered:
                _GROQ_LIVE_MODELS_CACHE = ordered
                return ordered
    except Exception as e:
        print(f"⚠️ 动态获取 Groq 模型列表失败: {e}")
    return ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]


def _request_openai_compatible(provider, model, messages, temperature=0.3, json_mode=False):
    api_key = LLM_API_KEYS.get(provider, "").strip()
    if not api_key:
        raise ValueError(f"未配置 {provider} 的 API Key")

    url = LLM_ENDPOINTS[provider]
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    if provider == "glm":
        models_to_try = [model, "glm-4-flash", "glm-4-flash-250414", "glm-4-air"]
    elif provider == "groq":
        live_models = _get_groq_live_models(api_key)
        models_to_try = [model] + [m for m in live_models if m != model]
    else:
        models_to_try = [model]

    seen = set()
    unique_models = [x for x in models_to_try if not (x in seen or seen.add(x))]
    last_error = None

    for m in unique_models:
        payload = {
            "model": m,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 2048,
        }
        if json_mode and provider in ["openai", "deepseek"]:
            payload["response_format"] = {"type": "json_object"}

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=35)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                if content:
                    return content
            else:
                last_error = f"{provider} ({m}) HTTP {resp.status_code}: {resp.text[:200]}"
                print(f"⚠️ {last_error}，尝试下一个候选模型...")
        except Exception as e:
            last_error = f"{provider} ({m}) 请求异常: {e}"
            print(f"⚠️ {last_error}，尝试下一个候选模型...")

    raise RuntimeError(last_error or f"{provider} 所有候选模型均调用失败")


def call_llm(agent_role="default", system_prompt="", user_prompt="", temperature=0.3, json_mode=False):
    route = AGENT_MODEL_ROUTING.get(agent_role, AGENT_MODEL_ROUTING["default"])
    primary_provider = route["provider"]
    primary_model = route["model"]

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    try:
        return _request_openai_compatible(
            primary_provider, primary_model, messages, temperature, json_mode
        )
    except Exception as e:
        print(f"⚠️ 主模型 [{primary_provider}:{primary_model}] 失败: {e} -> 正在切换备用平台...")

    fallback = AGENT_MODEL_ROUTING["fallback"]
    try:
        return _request_openai_compatible(
            fallback["provider"], fallback["model"], messages, temperature, json_mode
        )
    except Exception as e2:
        print(f"❌ 备用模型 [{fallback['provider']}:{fallback['model']}] 也调用失败: {e2}")

    for backup_prov, default_mod in [
        ("glm", "glm-4-flash"),
        ("groq", "llama-3.3-70b-versatile"),
        ("deepseek", "deepseek-chat"),
    ]:
        if LLM_API_KEYS.get(backup_prov) and backup_prov not in [primary_provider, fallback["provider"]]:
            try:
                return _request_openai_compatible(
                    backup_prov, default_mod, messages, temperature, json_mode
                )
            except Exception:
                continue

    return "{}" if json_mode else "模型调用失败，请检查 GLM_API_KEY 或 GROQ_API_KEY。"


def ask_ai(prompt, role="default", system_prompt="", temperature=0.3, json_mode=False):
    return call_llm(
        agent_role=role,
        system_prompt=system_prompt,
        user_prompt=prompt,
        temperature=temperature,
        json_mode=json_mode,
    )


def extract_json(text):
    if not text:
        return {}
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)

    start_brace = text.find("{")
    start_bracket = text.find("[")
    if start_brace == -1 and start_bracket == -1:
        return {}

    if start_bracket != -1 and (start_brace == -1 or start_bracket < start_brace):
        end_bracket = text.rfind("]")
        if end_bracket != -1:
            json_str = text[start_bracket : end_bracket + 1]
            try:
                return json.loads(json_str)
            except Exception:
                pass

    if start_brace != -1:
        end_brace = text.rfind("}")
        if end_brace != -1:
            json_str = text[start_brace : end_brace + 1]
            try:
                return json.loads(json_str)
            except Exception:
                pass
    return {}


def multi_agent_evaluate(project_data, evolution_state=None):
    """
    V6.0 进化记忆驱动的多智能体投委会辩论：
    - 将 job3 实盘回测总结的【最新进化铁律】注入多空与 CIO 脑中
    - 重点审计【是否处于发币/启动极早期】、【当前买点位置是否过高】、【市值赔率是否足够大】
    """
    if not isinstance(evolution_state, dict):
        evolution_state = DEFAULT_EVOLUTION_STATE

    tactical_rules = evolution_state.get("tactical_rules") or DEFAULT_EVOLUTION_STATE["tactical_rules"]
    evo_reason = evolution_state.get("evolution_reason") or DEFAULT_EVOLUTION_STATE["evolution_reason"]
    gen_num = evolution_state.get("generation", 1)
    rules_text = "\n".join([f"  - {r}" for r in tactical_rules])

    is_meme = project_data.get("is_meme_candidate", False)
    project_json = json.dumps(project_data, ensure_ascii=False, indent=2)

    if is_meme:
        bull_sys = (
            "你是顶级的链上极早期金狗与 Meme 狙击手（Degen Alpha Hunter）。"
            "你只对【刚开盘/刚启动早期、小市值($15万~$1500万)、买单明显压制卖单、换手健康】的早期高赔率金狗感兴趣。"
            "请结合档案中的上线账龄(age_label)、1h/6h/24h涨幅节奏、买卖比和叙事梗，用3点简明列出早期看多逻辑（130字内）。"
        )
        bear_sys = (
            "你是极其严酷的链上防追高与防派发审计员（Anti-FOMO Bear Agent）。"
            "请专门审计该项目是否存在以下致命问题：1. 已经错过发币早期最佳窗口？2. 24h或6h涨幅已经过高、存在庄家拉高派发让我们高位接盘的风险？3. 市值是否已经偏大或买盘衰竭？"
            "一针见血指出 2-3 个位置与筹码风险点（130字内）。"
        )
    else:
        bull_sys = (
            "你是专注于发掘早期低市值十倍黑马的加密 VC 狙击合伙人（Early Alpha Bull Agent）。"
            "你痛恨大市值老白马，专门寻找【市值$100万~$5000万、处于底部蓄势突破初期或新叙事刚点火、买盘刚放量】的高赔率项目。"
            "请结合档案中的建仓位置评级、市值赔率、催化剂与基本面，用3点提炼看涨逻辑（130字内）。"
        )
        bear_sys = (
            "你是严苛的加密基金买点风控总监（Position & Timing Bear Agent）。"
            "请专门审计：1. 该项目当前位置是否已经涨幅过大、属于右侧追高接盘？2. 市值是否过高导致赔率不足？3. 流通率(MC/FDV)解锁抛压或换手率是否存在诱多嫌疑？"
            "一针见血指出 2-3 个核心隐患（130字内）。"
        )

    bull_view = call_llm("bull_agent", bull_sys, f"【深度背调档案】:\n{project_json}", temperature=0.45)
    time.sleep(0.4)
    bear_view = call_llm(
        "bear_agent",
        bear_sys,
        f"【深度背调档案】:\n{project_json}\n\n【多头观点】:\n{bull_view}",
        temperature=0.35,
    )
    time.sleep(0.4)

    cio_sys = f"""你是加密基金首席投资官 (CIO)，当前智能体处于【第 Gen #{gen_num} 代高频进化状态】。
以下是系统根据近期实盘盈亏回测总结出的【本轮强制进化复盘结论与狙击铁律】，你必须严格执行：
【近期实盘进化复盘】：{evo_reason}
【本轮强制狙击铁律】：
{rules_text}

请综合【深度背调档案】与多空辩论，做出冷酷、敏锐的裁决：
1. 【买点位置与早期度一票否决权】：
   - 如果项目已经暴涨过高（处于高潮派发期）、或市值过大缺乏十倍赔率、或 1h/24h 卖盘大于买盘冲高回落，`ai_score` 必须打 **50~62 分（直接淘汰）**！
   - 只有真正处于【极早期启动窗口】、【底部黄金坑右侧刚放量拐点】或【低市值主升浪突破初期】、且买盘强劲的标的，才可给予 **75~95 分**！
2. 【分类验真铁律】：
   - 只有文化社区梗、动物币、名人梗、AI纯Meme或链上原生土狗，才归类为 `🐶 链上早期Meme/金狗`。
   - 有实际协议/产品业务的早期项目，归类为 `🚀 叙事异动黑马`、`📈 强势赛道龙头` 或 `💎 机构潜伏/底部价值`。
3. 【输出格式】：严格输出纯 JSON：
{{
  "ai_score": 84,
  "verdict": "极早期重仓狙击 / 黄金买点关注 / 位置偏高观望 / 高位接盘放弃",
  "entry_timing": "🟢 极早期点火窗口 或 💎 底部右侧拐点 或 🚀 突破启动初期 或 ⚠️ 涨幅偏高谨慎",
  "verified_type": "🐶 链上早期Meme/金狗 或 🚀 叙事异动黑马 或 📈 强势赛道龙头 或 💎 机构潜伏/底部价值",
  "verified_track": "精准的中文细分赛道名称(8字以内)",
  "catalyst": "一句话点明为什么现在是最佳进入窗口及核心催化剂(35字以内)",
  "summary": "明确给出最佳分批建仓区间、止盈目标位与跌破何处无条件止损（120字以内）"
}}"""

    cio_prompt = f"【深度背调档案】:\n{project_json}\n\n【多头观点】:\n{bull_view}\n\n【空头风控】:\n{bear_view}"
    cio_raw = call_llm("cio_agent", cio_sys, cio_prompt, temperature=0.2, json_mode=True)
    cio_data = extract_json(cio_raw) if isinstance(extract_json(cio_raw), dict) else {}

    try:
        raw_score = str(cio_data.get("ai_score", 72)).replace("分", "").strip()
        ai_score = float(raw_score)
    except Exception:
        ai_score = 72.0

    verdict = cio_data.get("verdict", "黄金买点关注")
    entry_timing = cio_data.get("entry_timing") or project_data.get("position_tag", "🟢 早期启动窗口")
    verified_type = cio_data.get("verified_type", "")
    verified_track = cio_data.get("verified_track", "")
    catalyst = cio_data.get("catalyst", "底部早期放量点火，买盘主动吸筹明显")
    summary = cio_data.get("summary", "建议在回踩5日均线或池子支撑位分批建仓，跌破前低8%严格止损。")

    valid_types = [
        "🐶 链上早期Meme/金狗",
        "🚀 叙事异动黑马",
        "📈 强势赛道龙头",
        "💎 机构潜伏/底部价值",
    ]
    if verified_type not in valid_types:
        verified_type = (
            "🐶 链上早期Meme/金狗"
            if is_meme
            else project_data.get("initial_opp_type", "🚀 叙事异动黑马")
        )

    report = (
        f"⏱️【窗口诊断 ({entry_timing})】: {catalyst}\n"
        f"🐂【早期看多】: {bull_view.strip()}\n"
        f"🐻【位置风控】: {bear_view.strip()}\n"
        f"⚖️【CIO裁决 ({verdict})】: {summary.strip()}"
    )
    return ai_score, report, verified_type, verified_track, catalyst, entry_timing
