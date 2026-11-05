# llm_engine.py
import json
import config
import requests


def _call_llm(provider_str, prompt, system_prompt):
  if ":" in provider_str:
    provider_name, model_name = provider_str.split(":", 1)
  else:
    provider_name = provider_str
    model_name = config.LLM_PROVIDERS[provider_name]["default_model"]

  cfg = config.LLM_PROVIDERS.get(provider_name)
  if not cfg or not cfg["api_key"]:
    raise ValueError(f"[{provider_name}] 未配置 API_KEY")

  headers = {
      "Content-Type": "application/json",
      "Authorization": f"Bearer {cfg['api_key']}",
  }
  payload = {
      "model": model_name,
      "messages": [
          {"role": "system", "content": system_prompt},
          {"role": "user", "content": prompt},
      ],
  }
  if "reasoner" not in model_name:
    payload["temperature"] = 0.6

  res = requests.post(
      cfg["base_url"], headers=headers, json=payload, timeout=60
  )
  res.raise_for_status()
  return res.json()["choices"][0]["message"]["content"]


def ask_ai(
    prompt, role="default", system_prompt="你是一个专业的加密货币投研智能体。"
):
  target = config.ROLE_MODELS.get(role, config.ROLE_MODELS["default"])
  try:
    return _call_llm(target, prompt, system_prompt)
  except Exception as e:
    fallback = config.ROLE_MODELS.get("fallback")
    print(f"⚠️ [{target}] 调用异常({e})，自动切换至保底模型 [{fallback}]...")
    return _call_llm(fallback, prompt, system_prompt)


def extract_json(text):
  """安全提取大模型返回的 JSON"""
  clean = text.replace("```json", "").replace("```", "").strip()
  start = clean.find("{") if "{" in clean else clean.find("[")
  end = clean.rfind("}") if "}" in clean else clean.rfind("]")
  return json.loads(clean[start : end + 1])


def multi_agent_evaluate(project_info_str):
  """三权分立多智能体投委会辩论"""
  bull_view = ask_ai(
      f"项目数据：\n{project_info_str}\n请扮演激进加密游资，只找亮点（如叙事风口、低市值高赔率、超跌安全垫、VC背书），列出3条看涨理由（150字内）。",
      role="bull_agent",
  )

  bear_view = ask_ai(
      f"项目数据：\n{project_info_str}\n请扮演华尔街做空机构，专门挑刺（如FDV解锁抛压、伪需求、流动性差、代码停滞），列出3条致命风险（150字内）。",
      role="bear_agent",
  )

  cio_prompt = f"""
    原始数据：{project_info_str}
    【游资多头观点】：{bull_view}
    【风控空头观点】：{bear_view}
    请作为基金首席投资官(CIO)，综合双方辩论给出客观裁决。严格输出纯 JSON 格式：
    {{
        "ai_score": 80,
        "summary_report": "【核心业务】...\\n【看多逻辑】...\\n【核心风险】...\\n【操作建议】..."
    }}
    """
  return extract_json(ask_ai(cio_prompt, role="cio_agent"))