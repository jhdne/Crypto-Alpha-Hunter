# config.py - V7.1 统一配置中心（$5W-$500W 早期高赔率窗口 + 自适应动量风控）
import os


def _env(key, default=""):
    val = os.getenv(key, default)
    return val.strip() if isinstance(val, str) else default


# ================= 1. 大模型配置中心 =================
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

AGENT_MODEL_ROUTING = {
    "default": {"provider": "glm", "model": "glm-4-flash"},
    "macro_analyst": {"provider": "glm", "model": "glm-4-flash"},
    "bull_agent": {"provider": "glm", "model": "glm-4-flash"},
    "bear_agent": {"provider": "glm", "model": "glm-4-flash"},
    "cio_agent": {"provider": "glm", "model": "glm-4-flash"},
    "cio_judge": {"provider": "glm", "model": "glm-4-flash"},
    "evolver_agent": {"provider": "glm", "model": "glm-4-flash"},
    "fallback": {"provider": "groq", "model": "llama-3.3-70b-versatile"},
}

# ================= 2. 进化默认基因参数（V7.1: 5W-500W 早期击球区） =================
DEFAULT_EVOLUTION_STATE = {
    "generation": 1,
    "last_evolved_at": "尚未触发回测",
    "win_rate_pct": 0.0,
    "avg_roi_pct": 0.0,
    "payoff_ratio": 1.0,
    "expectancy_pct": 0.0,
    "total_tested": 0,
    "best_pick": "暂无",
    "worst_pick": "暂无",
    "attribution_summary": "等待首轮实盘样本积累后生成策略归因。",
    "guardrails": {
        "min_mc_wan": 5.0,
        "max_meme_mc_wan": 500.0,
        "max_narrative_mc_wan": 500.0,
        "max_24h_pump_limit": 120.0,
        "sweet_spot_24h_max": 48.0,
        "min_buy_ratio_pct": 53.0,
        "min_score_threshold": 68.0,
    },
    "weights": {
        "early_timing": 0.30,
        "buy_pressure": 0.25,
        "mc_odds": 0.20,
        "track_heat": 0.15,
        "fundamentals": 0.10,
    },
    "evolution_reason": "V7.1 初始基因：聚焦 $5万~$500万 极早期高赔率击球区，采用结构化动量评估替代死板涨幅拦截，优先捕捉买盘持续、量价健康的早期启动标的。",
    "tactical_rules": [
        "【微盘高赔率区间】核心聚焦市值 $5万~$500万 的极早期新盘与价值黑马，后续由进化引擎根据实盘胜率与盈亏比动态微调区间。",
        "【弹性动量评估】24h 涨幅高并非绝对否决项；仅当 24h 涨幅过热且伴随 1h 转跌或买盘占比跌破 55% 的派发迹象时才一票否决。",
        "【多维交叉验真】优先放行同时命中链上真实放量、安全审计通过、热搜/VC 资金面共振的高置信度标的。",
    ],
}

# ================= 3. 飞书与外部数据源密钥 =================
FEISHU_APP_ID = _env("FEISHU_APP_ID")
FEISHU_APP_SECRET = _env("FEISHU_APP_SECRET")
FEISHU_APP_TOKEN = _env("FEISHU_APP_TOKEN")

TABLE_ID_CONFIG = _env("TABLE_ID_CONFIG")
TABLE_ID_RADAR = _env("TABLE_ID_RADAR")
TABLE_ID_ALPHA = _env("TABLE_ID_ALPHA")

FEISHU_URL = _env("FEISHU_URL", "https://feishu.cn")
FEISHU_DASHBOARD_URL = _env("FEISHU_DASHBOARD_URL") or FEISHU_URL
_raw_webhook = _env("FEISHU_WEBHOOK_URL")
if not _raw_webhook and "/open-apis/bot/v2/hook/" in FEISHU_URL:
    _raw_webhook = FEISHU_URL
FEISHU_WEBHOOK_URL = _raw_webhook

COINGECKO_API_KEY = _env("COINGECKO_API_KEY")
TAVILY_API_KEY = _env("TAVILY_API_KEY")
