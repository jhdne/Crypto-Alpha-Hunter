# config.py
import os


def _env(key, default=""):
    val = os.getenv(key, default)
    return val.strip() if isinstance(val, str) else default


# ================= 1. 大模型配置中心 (主用 GLM + 备用 Groq) =================
LLM_API_KEYS = {
    "glm": _env("GLM_API_KEY") or _env("ZHIPU_API_KEY"),
    "groq": _env("GROQ_API_KEY"),
    "deepseek": _env("DEEPSEEK_API_KEY"),
    "openai": _env("OPENAI_API_KEY"),
}

LLM_ENDPOINTS = {
    "glm": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "deepseek": "https://api.deepseek.com/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
}

# 所有任务优先使用 GLM，失败自动切换至 Groq
AGENT_MODEL_ROUTING = {
    "default": {"provider": "glm", "model": "glm-4-flash"},
    "bull_agent": {"provider": "glm", "model": "glm-4-flash"},
    "bear_agent": {"provider": "glm", "model": "glm-4-flash"},
    "cio_agent": {"provider": "glm", "model": "glm-4-flash"},
    "evolver_agent": {"provider": "glm", "model": "glm-4-flash"},
    "fallback": {"provider": "groq", "model": "llama-3.3-70b-versatile"},
}

# 保留旧版字典结构兼容
LLM_PROVIDERS = {
    "glm": {
        "base_url": LLM_ENDPOINTS["glm"],
        "api_key": LLM_API_KEYS["glm"],
        "default_model": "glm-4-flash",
    },
    "groq": {
        "base_url": LLM_ENDPOINTS["groq"],
        "api_key": LLM_API_KEYS["groq"],
        "default_model": "llama-3.3-70b-versatile",
    },
}

ROLE_MODELS = {
    "default": "glm",
    "bull_agent": "glm",
    "bear_agent": "glm",
    "cio_agent": "glm",
    "evolver_agent": "glm",
    "fallback": "groq",
}

# ================= 2. 飞书与外部数据源密钥 =================
FEISHU_APP_ID = _env("FEISHU_APP_ID")
FEISHU_APP_SECRET = _env("FEISHU_APP_SECRET")
FEISHU_APP_TOKEN = _env("FEISHU_APP_TOKEN")

TABLE_ID_CONFIG = _env("TABLE_ID_CONFIG")
TABLE_ID_RADAR = _env("TABLE_ID_RADAR")
TABLE_ID_ALPHA = _env("TABLE_ID_ALPHA")
FEISHU_URL = _env("FEISHU_URL", "https://feishu.cn")

COINGECKO_API_KEY = _env("COINGECKO_API_KEY")
TAVILY_API_KEY = _env("TAVILY_API_KEY")
