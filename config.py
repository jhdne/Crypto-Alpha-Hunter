# config.py
import os


def _env(key, default=""):
  val = os.getenv(key, default)
  return val.strip() if isinstance(val, str) else default


# ================= 1. 大模型配置中心 (主用 GLM + 备用 Groq) =================
LLM_PROVIDERS = {
    "glm": {
        # 智谱 AI 官方兼容接口
        "base_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "api_key": _env("GLM_API_KEY") or _env("ZHIPU_API_KEY"),
        "default_model": "glm-4.7-flash",
    },
    "groq": {
        # Groq 官方接口 (https://console.groq.com/)
        "base_url": "https://api.groq.com/openai/v1/chat/completions",
        "api_key": _env("GROQ_API_KEY"),
        "default_model": "llama-3.3-70b-versatile",  # Groq 上最聪明且免费的旗舰模型
    },
}

# ================= 2. 所有任务统一使用 GLM，失败自动切换 Groq =================
ROLE_MODELS = {
    "default": "glm",  # 赛道分析用 GLM
    "bull_agent": "glm",  # 看多游资用 GLM
    "bear_agent": "glm",  # 看空风控用 GLM
    "cio_agent": "glm",  # 首席投资官裁决用 GLM
    "evolver_agent": "glm",  # 自我进化用 GLM
    "fallback": "groq",  # 备用模型：一旦 GLM 报错或超限，自动切换至 Groq
}

# ================= 3. 飞书与外部数据源密钥 =================
FEISHU_APP_ID = _env("FEISHU_APP_ID")
FEISHU_APP_SECRET = _env("FEISHU_APP_SECRET")
FEISHU_APP_TOKEN = _env("FEISHU_APP_TOKEN")

TABLE_ID_CONFIG = _env("TABLE_ID_CONFIG")
TABLE_ID_RADAR = _env("TABLE_ID_RADAR")
TABLE_ID_ALPHA = _env("TABLE_ID_ALPHA")
FEISHU_URL = _env("FEISHU_URL", "https://feishu.cn")

COINGECKO_API_KEY = _env("COINGECKO_API_KEY")
TAVILY_API_KEY = _env("TAVILY_API_KEY")
