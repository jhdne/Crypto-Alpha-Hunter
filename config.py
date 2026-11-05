# config.py
import os

# ================= 1. 万能大模型提供商注册表 =================
LLM_PROVIDERS = {
    "gemini": {
        "base_url": (
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        ),
        "api_key": os.getenv("GEMINI_API_KEY", ""),
        "default_model": "Gemini 3.5 Flash-Lite",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/chat/completions",
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "default_model": "deepseek-chat",
    },
    "siliconflow": {
        "base_url": "https://api.siliconflow.cn/v1/chat/completions",
        "api_key": os.getenv("SILICON_API_KEY", ""),
        "default_model": "deepseek-ai/DeepSeek-V3",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1/chat/completions",
        "api_key": os.getenv("OPENROUTER_API_KEY", ""),
        "default_model": "anthropic/claude-3.5-sonnet",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1/chat/completions",
        "api_key": os.getenv("OPENAI_API_KEY", ""),
        "default_model": "gpt-4o-mini",
    },
}

# ================= 2. 智能体角色模型自由分配 =================
ROLE_MODELS = {
    "default": os.getenv("MODEL_DEFAULT", "gemini"),
    "bull_agent": os.getenv("MODEL_BULL", "gemini"),
    "bear_agent": os.getenv("MODEL_BEAR", "gemini"),
    "cio_agent": os.getenv("MODEL_CIO", "gemini"),
    "evolver_agent": os.getenv("MODEL_EVOLVER", "gemini"),
    "fallback": os.getenv("MODEL_FALLBACK", "gemini"),
}

# ================= 3. 飞书与外部数据源密钥 =================
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
FEISHU_APP_TOKEN = os.getenv("FEISHU_APP_TOKEN", "")

TABLE_ID_CONFIG = os.getenv("TABLE_ID_CONFIG", "")
TABLE_ID_RADAR = os.getenv("TABLE_ID_RADAR", "")
TABLE_ID_ALPHA = os.getenv("TABLE_ID_ALPHA", "")
FEISHU_URL = os.getenv("FEISHU_URL", "https://feishu.cn")

COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")