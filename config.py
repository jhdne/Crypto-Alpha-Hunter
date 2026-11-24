# config.py - V7.0 统一配置中心
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

# ================= 2. 进化默认基因参数 =================
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
        "max_meme_mc_wan": 1500.0,
        "max_narrative_mc_wan": 5000.0,
        "max_24h_pump_limit": 68.0,
        "sweet_spot_24h_max": 38.0,
        "min_buy_ratio_pct": 53.5,
        "min_score_threshold": 68.0,
    },
    "weights": {
        "early_timing": 0.30,
        "buy_pressure": 0.25,
        "mc_odds": 0.20,
        "track_heat": 0.15,
        "fundamentals": 0.10,
    },
    "evolution_reason": "V7.0 初始基因：全周期 Alpha 捕获，严禁追高 24h 暴涨超 68% 的高位派发币，重点狙击早期高赔率点火标的与低估值价值击球区。",
    "tactical_rules": [
        "【防追高铁律】凡是 24h 涨幅已超过 68% 且 1h 涨幅转负或买单占比下降的标的，一律判定为『错过最佳建仓窗口/庄家派发』，CIO 必须一票否决（打分 < 55）。",
        "【极早期偏好】优先放行池子刚创建 1h~96h 内、或市值在 $20万~$800万之间、1h 与 6h 温和放量上涨 (+2%~+25%) 的早期点火标的。",
        "【多维交叉验真】优先选择同时命中 2 个以上独立数据源（链上放量 + 热搜/VC/外部催化剂 + 合约安全通过）的高置信度标的。",
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
