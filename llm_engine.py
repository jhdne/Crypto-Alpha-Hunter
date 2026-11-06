# llm_engine.py - GLM (主) + Groq (备) 高可用版 V2
import json
import config
import requests

# GLM 优先你指定的 4.7，失败自动兼容官方免费模型
GLM_MODELS = ["glm-4.7-flash", "glm-4.5-flash", "glm-4-flash"]
# Groq 当前在服模型，已删除下架的 gemma2-9b-it
GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "openai/gpt-oss-120b",
    "qwen/qwen3-32b",
]

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30


def _request_chat(url, api_key, model_name, prompt, system_prompt):
  headers = {
      "Content-Type": "application/json",
      "Authorization": f"Bearer {api_key.strip()}",
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
  }
  payload = {
      "model": model_name,
      "messages": [
          {"role": "system", "content": system_prompt},
          {"role": "user", "content": prompt},
      ],
      "temperature": 0.6,
  }
  # connect 10s, read 30s，快速失败，不死等60s
  return requests.post(
      url, headers=headers, json=payload, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)
  )


def _is_model_not_found(status, text):
  t = text.lower()
  return status in (400, 404) and any(
      k in t
      for k in [
          "model", "not found", "does not exist",
          "decommission", "no longer supports",
          "invalid model", "model_not_found",
      ]
  )


def _call_glm(cfg, prompt, system_prompt):
  api_key = cfg.get("api_key", "").strip()
  if not api_key:
    raise ValueError("未配置 GLM_API_KEY")
  # 把 config 里的 default_model 放第一位
  default = cfg.get("default_model") or GLM_MODELS[0]
  models = [default] + [m for m in GLM_MODELS if m != default]

  last_err = None
  for m in models:
    print(f"🔵 尝试 GLM 模型 [{m}]...")
    try:
      res = _request_chat(cfg["base_url"], api_key, m, prompt, system_prompt)
    except requests.exceptions.Timeout as e:
      # 线路超时，换模型名没用，直接抛出去切 Groq
      raise TimeoutError(f"GLM网络超时({e})，需切换备用通道")
    if res.status_code == 200:
      print(f"✅ GLM [{m}] 调用成功")
      return res.json()["choices"][0]["message"]["content"]
    err_text = res.text[:500]
    print(f"⚠️ GLM [{m}] 返回 {res.status_code}: {err_text[:200]}")
    if res.status_code == 401:
      raise RuntimeError(f"GLM鉴权失败401，请检查GLM_API_KEY: {err_text[:200]}")
    if _is_model_not_found(res.status_code, err_text):
      last_err = err_text
      continue  # 模型名不对，才试下一个
    if res.status_code == 429:
      raise RuntimeError(f"GLM限流429: {err_text[:200]}")
    last_err = err_text
    break  # 500等其他错误，直接切Groq，不浪费时间
  raise RuntimeError(f"GLM 调用失败 ({last_err})")


def _call_groq(cfg, prompt, system_prompt):
  api_key = cfg.get("api_key", "").strip()
  if not api_key:
    raise ValueError("未配置 GROQ_API_KEY")
  default = cfg.get("default_model") or GROQ_MODELS[0]
  models = [default] + [m for m in GROQ_MODELS if m != default]

  last_err = None
  for m in models:
    print(f"🟠 尝试 Groq 备用模型 [{m}]...")
    try:
      res = _request_chat(cfg["base_url"], api_key, m, prompt, system_prompt)
    except requests.exceptions.Timeout:
      print(f"⚠️ Groq [{m}] 超时，试下一个...")
      last_err = "timeout"
      continue  # Groq快，超时可能是单模型拥堵，换小模型试试
    if res.status_code == 200:
      print(f"✅ Groq [{m}] 调用成功")
      return res.json()["choices"][0]["message"]["content"]
    err_text = res.text[:500]
    print(f"⚠️ Groq [{m}] 返回 {res.status_code}: {err_text[:200]}")
    if res.status_code == 401:
      raise RuntimeError(f"Groq鉴权失败401，请检查GROQ_API_KEY")
    # Groq 的 400/404/429 都继续试下一个，因为不同模型是不同限流池
    last_err = err_text
    continue
  raise RuntimeError(f"Groq备用通道全部失败 ({str(last_err)[:300]})")


def ask_ai(prompt, role="default", system_prompt="你是一个专业的加密货币投研智能体。"):
  try:
    return _call_glm(config.LLM_PROVIDERS["glm"], prompt, system_prompt)
  except Exception as e1:
    print(f"⚠️ 主模型 [GLM] 失败 ({e1})，切换至备用 [Groq]...")
    try:
      return _call_groq(config.LLM_PROVIDERS["groq"], prompt, system_prompt)
    except Exception as e2:
      raise RuntimeError(f"双通道均失败 | GLM: {e1} | Groq: {e2}")


def extract_json(text):
  clean = text.replace("```json", "").replace("```", "").strip()
  start_brace = clean.find("{")
  start_bracket = clean.find("[")
  if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
    start, end = start_brace, clean.rfind("}")
  else:
    start, end = start_bracket, clean.rfind("]")
  return json.loads(clean[start : end + 1])


def multi_agent_evaluate(project_info_str):
  bull_view = ask_ai(
      f"项目数据：\n{project_info_str}\n请扮演激进加密游资，只找亮点，列出3条看涨理由（150字内）。",
      role="bull_agent",
  )
  bear_view = ask_ai(
      f"项目数据：\n{project_info_str}\n请扮演华尔街做空机构，列出3条致命风险（150字内）。",
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
