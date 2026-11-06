# llm_engine.py - 专为 GLM (主) + Groq (备) 打造的双擎驱动器
import json
import config
import requests


def _request_chat(url, api_key, model_name, prompt, system_prompt):
  """底层通用请求：带有 User-Agent 伪装，防止 Groq 的 Cloudflare 防火墙报 403 拦截"""
  headers = {
      "Content-Type": "application/json",
      "Authorization": f"Bearer {api_key.strip()}",
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
      ),
  }
  payload = {
      "model": model_name,
      "messages": [
          {"role": "system", "content": system_prompt},
          {"role": "user", "content": prompt},
      ],
      "temperature": 0.6,
  }
  return requests.post(url, headers=headers, json=payload, timeout=60)


def _call_glm(cfg, prompt, system_prompt):
  """调用 GLM：优先尝试 glm-4.7-flash，若接口识别为 glm-4-flash 则自动兼容"""
  api_key = cfg.get("api_key", "").strip()
  if not api_key:
    raise ValueError("未配置 GLM_API_KEY")

  models_to_try = [cfg["default_model"], "glm-4-flash", "glm-4-flashx"]
  last_err = None
  for m in models_to_try:
    res = _request_chat(cfg["base_url"], api_key, m, prompt, system_prompt)
    if res.status_code == 200:
      return res.json()["choices"][0]["message"]["content"]
    else:
      last_err = f"HTTP {res.status_code}: {res.text[:200]}"
  raise RuntimeError(f"GLM 调用失败 ({last_err})")


def _call_groq(cfg, prompt, system_prompt):
  """调用备用平台 Groq：优先 llama-3.3-70b-versatile，备用 llama-3.1-8b-instant"""
  api_key = cfg.get("api_key", "").strip()
  if not api_key:
    raise ValueError("未配置 GROQ_API_KEY")

  models_to_try = [cfg["default_model"], "llama-3.1-8b-instant", "gemma2-9b-it"]
  last_err = None
  for m in models_to_try:
    res = _request_chat(cfg["base_url"], api_key, m, prompt, system_prompt)
    if res.status_code == 200:
      return res.json()["choices"][0]["message"]["content"]
    else:
      last_err = f"HTTP {res.status_code}: {res.text[:200]}"
  raise RuntimeError(f"Groq 备用平台调用失败 ({last_err})")


def ask_ai(
    prompt, role="default", system_prompt="你是一个专业的加密货币投研智能体。"
):
  """对外统一接口：优先调用 GLM，失败自动无缝切换至 Groq"""
  try:
    return _call_glm(config.LLM_PROVIDERS["glm"], prompt, system_prompt)
  except Exception as e:
    print(f"⚠️ 主模型 [GLM] 调用异常 ({e})，正在切换至备用平台 [Groq]...")
    return _call_groq(config.LLM_PROVIDERS["groq"], prompt, system_prompt)


def extract_json(text):
  """安全提取大模型返回的 JSON 数据"""
  clean = text.replace("```json", "").replace("```", "").strip()
  start_brace = clean.find("{")
  start_bracket = clean.find("[")
  if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
    start = start_brace
    end = clean.rfind("}")
  else:
    start = start_bracket
    end = clean.rfind("]")
  return json.loads(clean[start : end + 1])


def multi_agent_evaluate(project_info_str):
  """三权分立多智能体投委会辩论（均使用 GLM，Groq 保底）"""
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
    请作为基金首席投资官(CIO)，综合双方辩论给出客观裁决。严格输出纯 JSON 格式（不要输出任何多余解释）：
    {{
        "ai_score": 80,
        "summary_report": "【核心业务】...\\n【看多逻辑】...\\n【核心风险】...\\n【操作建议】..."
    }}
    """
  return extract_json(ask_ai(cio_prompt, role="cio_agent"))
