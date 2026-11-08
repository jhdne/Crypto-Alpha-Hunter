```python
import json
import re
import time
import requests
from config import LLM_API_KEYS, LLM_ENDPOINTS, AGENT_MODEL_ROUTING

_GROQ_LIVE_MODELS_CACHE = None

def _get_groq_live_models(api_key):
    """动态拉取 Groq 当前在线的可用模型列表"""
    global _GROQ_LIVE_MODELS_CACHE
    if _GROQ_LIVE_MODELS_CACHE:
        return _GROQ_LIVE_MODELS_CACHE
    try:
        resp = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            models = [
                m["id"] for m in data
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
                "llama3-8b-8192"
            ]
            ordered = [m for m in preferred if m in models] + [m for m in models if m not in preferred]
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
        "Authorization": f"Bearer {api_key}"
    }

    if provider == "glm":
        models_to_try = [model, "glm-4-flash", "glm-4-flash-250414"]
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
            "max_tokens": 2048
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
        return _request_openai_compatible(primary_provider, primary_model, messages, temperature, json_mode)
    except Exception as e:
        print(f"⚠️ 主模型 [{primary_provider}:{primary_model}] 失败: {e} -> 正在切换备用平台...")

    fallback = AGENT_MODEL_ROUTING["fallback"]
    try:
        return _request_openai_compatible(fallback["provider"], fallback["model"], messages, temperature, json_mode)
    except Exception as e2:
        print(f"❌ 备用模型 [{fallback['provider']}:{fallback['model']}] 也调用失败: {e2}")

    for backup_prov, default_mod in [("glm", "glm-4-flash"), ("groq", "llama-3.3-70b-versatile"), ("deepseek", "deepseek-chat")]:
        if LLM_API_KEYS.get(backup_prov) and backup_prov not in [primary_provider, fallback["provider"]]:
            try:
                return _request_openai_compatible(backup_prov, default_mod, messages, temperature, json_mode)
            except Exception:
                continue

    return "{}" if json_mode else "模型调用失败，请检查 GLM_API_KEY 或 GROQ_API_KEY。"


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
            json_str = text[start_bracket:end_bracket + 1]
            try:
                return json.loads(json_str)
            except Exception:
                pass

    if start_brace != -1:
        end_brace = text.rfind("}")
        if end_brace != -1:
            json_str = text[start_brace:end_brace + 1]
            try:
                return json.loads(json_str)
            except Exception:
                pass
    return {}


def multi_agent_evaluate(project_data):
    """
    V5.0 双模式多智能体投委会辩论（自动区分【链上早期Meme】与【叙事/价值项目】）
    同时基于深度背调数据验真项目的【真实机会类型】与【精准细分赛道】
    """
    is_meme = project_data.get("is_meme_candidate", False)
    project_json = json.dumps(project_data, ensure_ascii=False, indent=2)

    if is_meme:
        # 模式 A：链上早期 Meme / 金狗专属投委会
        bull_sys = (
            "你是顶级的链上金狗与 Meme 币早期狙击手（Degen Alpha Hunter）。"
            "你极其擅长从链上流动性、买卖单笔数比（Buys vs Sells）、短时爆发换手率、社区文化梗（Meme 叙事传播力）中发掘早期 10x 金狗。"
            "注意：Meme 币不需要看 GitHub 代码提交，重点看叙事传播度、买盘强度和筹码换手。请用3点简明扼要列出看多逻辑（150字内）。"
        )
        bear_sys = (
            "你是冷酷的链上风控与防貔貅/防砸盘审计员。"
            "请根据项目的池子流动性大小、FDV市值比、短时涨幅是否过热、是否存在庄家拉高出货（阴跌或卖单激增）风险，"
            "一针见血指出 2-3 个最大风险点（150字内）。"
        )
    else:
        # 模式 B：早期高赔率叙事黑马 / 赛道价值投委会
        bull_sys = (
            "你是专注于发掘早期百倍币的加密 VC 激进派合伙人（Bull Agent）。"
            "请结合深度背调档案中的真实业务简介、所属细分赛道、近期催化剂新闻、市值赔率空间、开发活跃度或机构背书，"
            "用3点简明扼要提炼该项目最具爆发力的看涨逻辑（150字内）。"
        )
        bear_sys = (
            "你是严苛的加密基金风控总监（Bear Agent）。"
            "请根据项目的流通率(MC/FDV)解锁抛压、换手率真实性、代码提交情况、赛道竞争格局以及短期追高风险，"
            "一针见血指出 2-3 个核心隐患（150字内）。"
        )

    bull_view = call_llm("bull_agent", bull_sys, f"【深度背调档案】:\n{project_json}", temperature=0.5)
    time.sleep(0.5)
    bear_view = call_llm("bear_agent", bear_sys, f"【深度背调档案】:\n{project_json}\n\n【多头观点】:\n{bull_view}", temperature=0.4)
    time.sleep(0.5)

    cio_sys = """你是加密基金首席投资官 (CIO)。请阅读项目【深度背调档案】以及多空双方辩论，做出最终裁决并完成严格分类验真：
1. 【分类验真铁律】：
   - 仔细核对档案中的 `coingecko_categories`、`description` 和 `onchain_metrics`。
   - 只有真正属于文化社区梗、动物币、名人梗、AI纯Meme或链上原生土狗的项目，才能归类为 `🐶 链上早期Meme/金狗`。
   - 如果是公链(L1/L2)、DeFi、AI基础设施/Agent工具、DePIN、RWA、游戏、预言机等有实际产品业务的异动项目，必须归类为 `🚀 叙事异动黑马`、`📈 强势赛道龙头` 或 `💎 机构潜伏/底部价值`，绝不能错标为 Meme！
2. 【精准赛道提炼】：
   - 根据背调信息给出准确的中文细分赛道名称 `verified_track`（例如：`Solana 链上Meme`、`Base 生态金狗`、`AI Agent 协议`、`RWA 美债协议`、`DePIN 算力网络`、`模块化区块链` 等，严禁输出“全网热搜异动榜”这种笼统假词）。
3. 【输出格式】：严格输出 JSON，不要夹杂任何解释：
{
  "ai_score": 82,
  "verdict": "强烈推荐 / 建议关注 / 谨慎观望 / 放弃",
  "verified_type": "🐶 链上早期Meme/金狗 或 🚀 叙事异动黑马 或 📈 强势赛道龙头 或 💎 机构潜伏/底部价值",
  "verified_track": "精准的中文细分赛道名称(8字以内)",
  "catalyst": "一句话点明该项目当前最核心的上涨催化剂或基本面亮点(35字以内)",
  "summary": "综合多空双方与背调档案的最终实战操作建议（含理想介入策略与止损风控，120字以内）"
}"""

    cio_prompt = f"【深度背调档案】:\n{project_json}\n\n【多头观点】:\n{bull_view}\n\n【空头风控】:\n{bear_view}"
    cio_raw = call_llm("cio_agent", cio_sys, cio_prompt, temperature=0.2, json_mode=True)
    cio_data = extract_json(cio_raw)

    ai_score = float(cio_data.get("ai_score", 70))
    verdict = cio_data.get("verdict", "建议关注")
    verified_type = cio_data.get("verified_type", "")
    verified_track = cio_data.get("verified_track", "")
    catalyst = cio_data.get("catalyst", "资金异动明显，具备短期博弈价值")
    summary = cio_data.get("summary", "请结合盘面量能与止损纪律分批参与。")

    valid_types = ["🐶 链上早期Meme/金狗", "🚀 叙事异动黑马", "📈 强势赛道龙头", "💎 机构潜伏/底部价值"]
    if verified_type not in valid_types:
        verified_type = "🐶 链上早期Meme/金狗" if is_meme else project_data.get("initial_opp_type", "🚀 叙事异动黑马")

    report = (
        f"🔥【核心催化】: {catalyst}\n"
        f"🐂【多头逻辑】: {bull_view.strip()}\n"
        f"🐻【空头风控】: {bear_view.strip()}\n"
        f"⚖️【CIO裁决 ({verdict})】: {summary.strip()}"
    )
    return ai_score, report, verified_type, verified_track, catalyst
```

---
