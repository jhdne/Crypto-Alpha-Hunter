# config.py - V6.0 配置中心与初始高频进化基因默认参数
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

AGENT_MODEL_ROUTING = {
    "default": {"provider": "glm", "model": "glm-4-flash"},
    "bull_agent": {"provider": "glm", "model": "glm-4-flash"},
    "bear_agent": {"provider": "glm", "model": "glm-4-flash"},
    "cio_agent": {"provider": "glm", "model": "glm-4-flash"},
    "evolver_agent": {"provider": "glm", "model": "glm-4-flash"},
    "fallback": {"provider": "groq", "model": "llama-3.3-70b-versatile"},
}

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

# ================= 2. V6.0 极早期狙击与高频自我进化默认基因参数 =================
DEFAULT_EVOLUTION_STATE = {
    "generation": 1,
    "last_evolved_at": "尚未触发回测",
    "win_rate_pct": 0.0,
    "avg_roi_pct": 0.0,
    "total_tested": 0,
    "best_pick": "暂无",
    "worst_pick": "暂无",
    # 动态硬性风控闸门（由 job3_self_evolver 根据实盘盈亏每 4 小时自动微调）
    "guardrails": {
        "max_meme_mc_wan": 1500.0,        # Meme 最大流通市值上限：1500万美元 ($15M)，聚焦早期高赔率
        "max_narrative_mc_wan": 5000.0,   # 叙事黑马最大流通市值上限：5000万美元 ($50M)，拒绝大市值老白马
        "max_24h_pump_limit": 68.0,       # 24h 最大涨幅防追高红线：超过 68% 视为错过最佳买点（除非极早期小盘强买盘）
        "sweet_spot_24h_max": 38.0,       # 最佳右侧启动涨幅甜蜜区上限：-5% ~ +38%
        "min_buy_ratio_pct": 53.5,        # 链上 24h/1h 最低买单占比：>= 53.5% 确保主力在吸筹而非派发
        "min_score_threshold": 68.0,      # 入选最低综合评分门槛
    },
    # 5 维动态评分权重（总和 = 1.0）
    "weights": {
        "early_timing": 0.30,             # 早期时机与买点位置安全度（最高优先级）
        "buy_pressure": 0.25,             # 链上真实买盘压制与换手爆发力
        "mc_odds": 0.20,                  # 小市值高赔率空间
        "track_heat": 0.15,               # 赛道与叙事催化剂热度
        "fundamentals": 0.10,             # 技术提交/机构背书/流通率结构
    },
    "evolution_reason": "V6.0 初始基因：严禁追高24h暴涨超68%的高位派发币，重点狙击市值$20万~$1500万、上线早期或底部刚放量突破、1h买盘占比>53.5%的黄金建仓窗口标的。",
    "tactical_rules": [
        "【防追高铁律】凡是24h涨幅已超过68%且1h涨幅转负或买单占比下降的标的，一律判定为『错过最佳建仓窗口/庄家派发』，CIO必须一票否决（打分<55）。",
        "【极早期偏好】优先放行池子刚创建1h~96h内、或市值在$20万~$800万之间、1h与6h温和放量上涨(+2%~+25%)的早期点火标的。",
        "【真买盘验真】链上24h买单笔数占比低于50%（卖盘大于买盘）的冲高回落项目，严禁入选。",
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

COINGECKO_API_KEY = _env("COINGECKO_API_KEY")
TAVILY_API_KEY = _env("TAVILY_API_KEY")
