import datetime
import json
import os
import re
import time
import requests
from config import (
    FEISHU_URL,
    TAVILY_API_KEY,
    DEFAULT_EVOLUTION_STATE,
)
from feishu_db import FeishuDB
from llm_engine import multi_agent_evaluate
from notifier import build_dashboard

LOCAL_DB_PATH = "docs/alpha_db.json"

# 彻底拉黑大市值老币、稳定币与主流公链币，只抓高赔率新锐标的
MEGA_CAP_BLACKLIST = {
    "btc", "eth", "sol", "bnb", "xrp", "ada", "doge", "trx", "ton", "link",
    "avax", "shib", "sui", "dot", "bch", "near", "ltc", "uni", "pepe", "apt",
    "icp", "etc", "tao", "fet", "render", "kas", "wif", "bonk", "floki", "arb",
    "op", "inj", "sei", "tia", "stx", "fil", "atom", "imx", "aa", "mkr", "ldo",
    "usdt", "usdc", "dai", "fdusd", "usde", "wbtc", "weth", "wsol", "wbnb",
    "gala", "sand", "mana", "axs", "ape", "chz", "eos", "xlm", "hbar", "vet",
    "algo", "flow", "theta", "egld", "xtz", "mina", "rose", "kava", "zil", "ens",
    "crv", "snx", "comp", "1inch", "sushi", "cake", "gmx", "dydx", "pendle",
    "ena", "ethfi", "eigen", "strk", "zk", "zro", "wormhole", "jup", "pyth",
    "ondo", "jasmy", "not", "dogs", "hmstr", "cat", "popcat", "mew", "brett",
    "mog", "neiro", "turbo", "bome", "sloth", "myro", "wen", "trump", "melania",
}


def load_local_db() -> dict:
    if os.path.exists(LOCAL_DB_PATH):
        try:
            with open(LOCAL_DB_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            print(f"⚠️ 读取 {LOCAL_DB_PATH} 异常: {e}")
    return {
        "updated_at": "",
        "hot_keywords": [],
        "vc_And_news": [],
        "tracks": [],
        "projects": [],
        "evolution_state": DEFAULT_EVOLUTION_STATE,
    }


def get_active_evolution_state(local_db: dict) -> dict:
    """获取最新的自我进化状态与风控闸门参数"""
    state = dict(DEFAULT_EVOLUTION_STATE)
    saved = local_db.get("evolution_state")
    if isinstance(saved, dict):
        state.update(saved)
        guardrails = dict(DEFAULT_EVOLUTION_STATE["guardrails"])
        if isinstance(saved.get("guardrails"), dict):
            guardrails.update(saved["guardrails"])
        state["guardrails"] = guardrails

        weights = dict(DEFAULT_EVOLUTION_STATE["weights"])
        if isinstance(saved.get("weights"), dict):
            weights.update(saved["weights"])
        state["weights"] = weights
    return state


def _calc_pool_age_hours(created_at_val) -> float:
    """计算池子上线至今的小时数（兼容 ISO 时间戳与毫秒时间戳）"""
    if not created_at_val:
        return 72.0
    now_ts = time.time()
    try:
        if isinstance(created_at_val, (int, float)):
            ts = float(created_at_val)
            if ts > 1e11:  # 毫秒时间戳
                ts /= 1000.0
            return max(0.2, (now_ts - ts) / 3600.0)
        if isinstance(created_at_val, str):
            s = created_at_val.replace("Z", "+00:00")
            dt = datetime.datetime.fromisoformat(s)
            return max(0.2, (now_ts - dt.timestamp()) / 3600.0)
    except Exception:
        pass
    return 72.0


def _format_age_label(hours: float) -> str:
    if hours < 1.0:
        return f"{int(hours * 60)}分钟(极早期)"
    if hours < 24.0:
        return f"{hours:.1f}小时(首日新盘)"
    if hours < 72.0:
        return f"{hours / 24.0:.1f}天(早期发酵)"
    if hours < 240.0:
        return f"{hours / 24.0:.1f}天(次新轮动)"
    return f"{int(hours / 24.0)}天"


def scan_gecko_pools(endpoint_type: str = "new_pools", pages: int = 2) -> list:
    """
    扫描 GeckoTerminal 链上池子：
    - new_pools: 刚创建不久的极早期新池子（抓第一波点火）
    - trending_pools: 正在放量的热门池子（抓底部右侧突破）
    """
    results = []
    headers = {"Accept": "application/json;version=20230302"}

    for page in range(1, pages + 1):
        url = f"https://api.geckoterminal.com/api/v2/networks/{endpoint_type}?include=base_token&page={page}"
        try:
            resp = requests.get(url, headers=headers, timeout=12)
            if resp.status_code != 200:
                continue
            payload = resp.json()
            data = payload.get("data", []) or []
            included = payload.get("included", []) or []

            token_meta = {}
            for inc in included:
                if inc.get("type") == "token":
                    tid = inc.get("id", "")
                    attrs = inc.get("attributes", {}) or {}
                    token_meta[tid] = {
                        "symbol": str(attrs.get("symbol", "")).strip(),
                        "name": str(attrs.get("name", "")).strip(),
                        "address": str(attrs.get("address", "")).strip(),
                    }

            for item in data:
                attrs = item.get("attributes", {}) or {}
                rels = item.get("relationships", {}) or {}
                base_id = (
                    rels.get("base_token", {}).get("data", {}).get("id", "")
                )
                net_id = (
                    rels.get("network", {}).get("data", {}).get("id", "")
                )
                if not net_id and "_" in base_id:
                    net_id = base_id.split("_")[0]

                meta = token_meta.get(base_id, {})
                pool_name = str(attrs.get("name", ""))
                symbol = meta.get("symbol") or (pool_name.split("/")[0].strip() if "/" in pool_name else pool_name)
                name = meta.get("name") or symbol
                contract = meta.get("address") or (base_id.split("_", 1)[1] if "_" in base_id else "")

                price_usd = float(attrs.get("base_token_price_usd") or 0.0)
                mc_usd = float(attrs.get("market_cap_usd") or attrs.get("fdv_usd") or 0.0)
                liq_usd = float(attrs.get("reserve_in_usd") or 0.0)

                vol_map = attrs.get("volume_usd", {}) or {}
                vol_24h = float(vol_map.get("h24") or 0.0)
                vol_1h = float(vol_map.get("h1") or 0.0)

                chg_map = attrs.get("price_change_percentage", {}) or {}
                chg_1h = float(chg_map.get("h1") or 0.0)
                chg_6h = float(chg_map.get("h6") or 0.0)
                chg_24h = float(chg_map.get("h24") or 0.0)

                txns_24h = (attrs.get("transactions", {}) or {}).get("h24", {}) or {}
                buys = int(txns_24h.get("buys") or 0)
                sells = int(txns_24h.get("sells") or 0)
                total_tx = buys + sells
                buy_ratio = round((buys / total_tx) * 100, 1) if total_tx > 0 else 50.0

                pool_age_h = _calc_pool_age_hours(attrs.get("pool_created_at"))
                pool_addr = str(attrs.get("address", ""))

                results.append(
                    {
                        "name": name,
                        "symbol": symbol.upper(),
                        "chain": net_id or "solana",
                        "contract": contract,
                        "price": price_usd,
                        "mc_usd": mc_usd,
                        "liq_usd": liq_usd,
                        "vol_24h": vol_24h,
                        "vol_1h": vol_1h,
                        "chg_1h": chg_1h,
                        "chg_6h": chg_6h,
                        "chg_24h": chg_24h,
                        "buys_24h": buys,
                        "sells_24h": sells,
                        "buy_ratio": buy_ratio,
                        "pool_age_hours": pool_age_h,
                        "age_label": _format_age_label(pool_age_h),
                        "source": f"Gecko_{endpoint_type}",
                        "dex_url": f"https://www.geckoterminal.com/{net_id}/pools/{pool_addr}" if net_id and pool_addr else f"https://dexscreener.com/search?q={contract}",
                    }
                )
        except Exception as e:
            print(f"⚠️ GeckoTerminal ({endpoint_type} p{page}) 扫描异常: {e}")
    return results


def scan_dexscreener_early_gems(keywords: list) -> list:
    """
    结合 DexScreener 最新 Token Boosts 与早期叙事关键词搜索，挖掘刚启动的小市值标的
    """
    results = []
    seen_pairs = set()

    # 1. 获取 DexScreener 最新异动 Token Boosts
    try:
        boost_resp = requests.get("https://api.dexscreener.com/token-boosts/top/v1", timeout=10)
        if boost_resp.status_code == 200:
            boosts = boost_resp.json()
            if isinstance(boosts, list):
                addrs = [b.get("tokenAddress") for b in boosts[:15] if b.get("tokenAddress")]
                if addrs:
                    chunk = ",".join(addrs[:10])
                    p_resp = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{chunk}", timeout=10)
                    if p_resp.status_code == 200:
                        for pair in (p_resp.json().get("pairs") or [])[:25]:
                            parsed = _parse_dexscreener_pair(pair)
                            if parsed and parsed["contract"] not in seen_pairs:
                                seen_pairs.add(parsed["contract"])
                                results.append(parsed)
    except Exception as e:
        print(f"⚠️ DexScreener Boosts 扫描异常: {e}")

    # 2. 按早期热词搜索刚启动的新池子
    search_terms = [k for k in keywords[:5] if k] + ["ai agent", "desci", "rwa"]
    for kw in search_terms[:6]:
        try:
            url = f"https://api.dexscreener.com/latest/dex/search?q={requests.utils.quote(str(kw))}"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                pairs = (resp.json().get("pairs") or [])[:12]
                for pair in pairs:
                    parsed = _parse_dexscreener_pair(pair, matched_kw=str(kw))
                    if parsed and parsed["contract"] not in seen_pairs:
                        seen_pairs.add(parsed["contract"])
                        results.append(parsed)
        except Exception:
            continue

    return results


def _parse_dexscreener_pair(pair: dict, matched_kw: str = "") -> dict:
    try:
        base = pair.get("baseToken", {}) or {}
        symbol = str(base.get("symbol", "")).strip().upper()
        name = str(base.get("name", "")).strip() or symbol
        contract = str(base.get("address", "")).strip()
        if not symbol or not contract:
            return None

        chain = str(pair.get("chainId", "solana")).lower()
        price = float(pair.get("priceUsd") or 0.0)
        mc_usd = float(pair.get("marketCap") or pair.get("fdv") or 0.0)
        liq_usd = float((pair.get("liquidity", {}) or {}).get("usd") or 0.0)

        vol_map = pair.get("volume", {}) or {}
        vol_24h = float(vol_map.get("h24") or 0.0)
        vol_1h = float(vol_map.get("h1") or 0.0)

        chg_map = pair.get("priceChange", {}) or {}
        chg_1h = float(chg_map.get("h1") or 0.0)
        chg_6h = float(chg_map.get("h6") or 0.0)
        chg_24h = float(chg_map.get("h24") or 0.0)

        tx_24h = (pair.get("txns", {}) or {}).get("h24", {}) or {}
        buys = int(tx_24h.get("buys") or 0)
        sells = int(tx_24h.get("sells") or 0)
        total_tx = buys + sells
        buy_ratio = round((buys / total_tx) * 100, 1) if total_tx > 0 else 50.0

        pool_age_h = _calc_pool_age_hours(pair.get("pairCreatedAt"))
        dex_url = str(pair.get("url") or f"https://dexscreener.com/{chain}/{contract}")

        return {
            "name": name,
            "symbol": symbol,
            "chain": chain,
            "contract": contract,
            "price": price,
            "mc_usd": mc_usd,
            "liq_usd": liq_usd,
            "vol_24h": vol_24h,
            "vol_1h": vol_1h,
            "chg_1h": chg_1h,
            "chg_6h": chg_6h,
            "chg_24h": chg_24h,
            "buys_24h": buys,
            "sells_24h": sells,
            "buy_ratio": buy_ratio,
            "pool_age_hours": pool_age_h,
            "age_label": _format_age_label(pool_age_h),
            "matched_kw": matched_kw,
            "source": "DexScreener",
            "dex_url": dex_url,
        }
    except Exception:
        return None


def classify_project_and_track(item: dict, approved_tracks: list, hot_keywords: list) -> tuple:
    """判断项目属于『🏛️ 叙事价值』还是『🌪️ 高波Meme』，并匹配细分赛道"""
    text = f"{item.get('name', '')} {item.get('symbol', '')} {item.get('matched_kw', '')}".lower()

    narrative_rules = [
        ("AI Agent", ["ai", "agent", "gpt", "neural", "autonomous", "bot", "eliza", "swarm", "agi"]),
        ("DePIN / 算力", ["depin", "gpu", "compute", "node", "network", "render", "wireless", "iot"]),
        ("RWA / PayFi", ["rwa", "real world", "treasury", "yield", "payfi", "credit", "gold", "bond"]),
        ("DeSci", ["desci", "bio", "longevity", "science", "molecule", "gene", "med", "quantum"]),
        ("BTCFi / 模块化L2", ["btcfi", "zk", "rollup", "modular", "layer2", "restaking", "omni", "bridge"]),
        ("DeFi 协议", ["swap", "dex", "perp", "lend", "stake", "liquidity", "vault", "protocol"]),
    ]

    for track_name, kw_list in narrative_rules:
        if any(k in text for k in kw_list):
            if item.get("mc_usd", 0) >= 1500000 and item.get("liq_usd", 0) >= 80000:
                return "🏛️ 叙事价值", track_name
            return "🌪️ 高波Meme", f"{track_name}概念"

    for t in approved_tracks:
        if t.lower() in text:
            return "🏛️ 叙事价值", t

    for hk in hot_keywords:
        if hk.lower() in text:
            return "🌪️ 高波Meme", f"{hk.upper()}热点"

    chain_label = str(item.get("chain", "Solana")).capitalize()
    return "🌪️ 高波Meme", f"{chain_label} 早期新盘"


def assess_entry_position(item: dict, guardrails: dict, is_meme: bool) -> tuple:
    """
    V6.0 核心防追高与早期买点识别器（解决『买在暴涨高位、错过极早期、市值过大』三大痛点）：
    返回: (is_valid: bool, entry_timing_label: str, timing_score: float, reject_reason: str)
    """
    chg_1h = item.get("chg_1h", 0.0)
    chg_6h = item.get("chg_6h", 0.0)
    chg_24h = item.get("chg_24h", 0.0)
    buy_ratio = item.get("buy_ratio", 50.0)
    mc_usd = item.get("mc_usd", 0.0)
    pool_age_h = item.get("pool_age_hours", 72.0)

    max_24h_pump = float(guardrails.get("max_24h_pump_limit", 68.0))
    sweet_24h_max = float(guardrails.get("sweet_spot_24h_max", 38.0))
    min_buy_ratio = float(guardrails.get("min_buy_ratio_pct", 53.5))

    # 1. 铁律拦截：买盘占比不足（主力在派发或无人问津）
    if buy_ratio < min_buy_ratio:
        return False, "", 0.0, f"买盘占比偏弱({buy_ratio:.1f}% < {min_buy_ratio}%)"

    # 2. 铁律拦截：已经处于暴涨拉高派发期（1h 掉头急跌且 24h 涨幅已高）
    if chg_24h > 25.0 and chg_1h < -4.0:
        return False, "", 0.0, f"高位放量派发迹象(24h+{chg_24h:.1f}%, 1h{chg_1h:.1f}%)"

    # 3. 铁律拦截：单日暴涨透支，严禁追高当流动性退出
    # 唯一例外：刚上线不到 24 小时、市值低于 $300万、买盘极强(>58%)且1h仍在稳步向上的极早期新池
    is_ultra_early_ignition = (
        pool_age_h <= 24.0
        and mc_usd <= 3000000
        and buy_ratio >= 58.0
        and 1.0 <= chg_1h <= 28.0
        and chg_24h <= (max_24h_pump * 1.35)
    )
    if chg_24h > max_24h_pump and not is_ultra_early_ignition:
        return False, "", 0.0, f"24h涨幅过高(+{chg_24h:.1f}% > +{max_24h_pump:.0f}%)，拒绝追高接盘"

    # 4. 铁律拦截：1小时瞬间暴拉过猛（防夹子与短线见顶针）
    if chg_1h > 35.0:
        return False, "", 0.0, f"1h短线急拉过猛(+{chg_1h:.1f}%)，防冲高回落"

    # 5. 铁律拦截：持续阴跌无承接
    if chg_24h < -22.0 or (chg_6h < -12.0 and chg_1h < 0):
        return False, "", 0.0, f"趋势走弱阴跌(24h {chg_24h:.1f}%)"

    # ========== 黄金买点分类与打分（满分 100） ==========
    # 形态 A：🟢 新币极早期点火窗口（上线 <= 48h，市值小，刚启动不远）
    if pool_age_h <= 48.0 and -5.0 <= chg_24h <= sweet_24h_max and chg_1h >= 0.8 and buy_ratio >= 55.0:
        return True, "🟢 新币极早期点火窗口", 95.0, ""

    # 形态 B：🟢 底部刚启动第1根阳线（24h 涨幅温和 0%~25%，1h 刚开始温和放量抬头 1.5%~18%）
    if -2.0 <= chg_24h <= 25.0 and 1.2 <= chg_1h <= 18.0 and buy_ratio >= 54.5:
        return True, "🟢 底部刚启动首阳买点", 92.0, ""

    # 形态 C：💎 强势洗盘缩量回调黄金坑（24h 温和收涨或微跌，6h 洗盘回调，1h 重新转正企稳且买盘>55%）
    if -12.0 <= chg_24h <= 30.0 and -10.0 <= chg_6h <= 2.0 and 0.5 <= chg_1h <= 12.0 and buy_ratio >= 55.0:
        return True, "💎 缩量回调企稳黄金坑", 88.0, ""

    # 形态 D：🚀 右侧温和放量突破期（涨幅在甜点区内，各周期稳步向上）
    if 0.0 <= chg_24h <= sweet_24h_max and 0.5 <= chg_1h <= 22.0:
        return True, "🚀 右侧温和放量突破期", 84.0, ""

    # 形态 E：🔥 极早期新盘首日发酵（满足超早期豁免条件）
    if is_ultra_early_ignition:
        return True, "🔥 首日新盘强势点火期", 82.0, ""

    # 形态 F：常规早期右侧区间（未超防追高红线，且 1h 为正）
    if chg_1h >= 0.0 and chg_24h <= max_24h_pump:
        return True, "🟢 早期右侧温和跟进", 74.0, ""

    return False, "", 0.0, "未出现明确早期启动或企稳信号"


def calculate_quant_score(
    item: dict,
    timing_score: float,
    weights: dict,
    is_meme: bool,
    approved_tracks: list,
    hot_keywords: list,
) -> float:
    """
    V6.0 五维早期高赔率量化评分（0~100）：
    - early_timing (30%): 买点位置与池子新鲜度
    - buy_pressure (25%): 主动买盘占比与量价换手活跃度
    - mc_odds (20%): 市值赔率空间（市值越小且流动性健康，赔率分越高）
    - track_heat (15%): 早期赛道与热词共振
    - fundamentals (10%): 交易笔数与深度健康度
    """
    w_timing = float(weights.get("early_timing", 0.30))
    w_buy = float(weights.get("buy_pressure", 0.25))
    w_mc = float(weights.get("mc_odds", 0.20))
    w_track = float(weights.get("track_heat", 0.15))
    w_fund = float(weights.get("fundamentals", 0.10))

    # 1. 买点与早期新鲜度得分
    pool_age_h = item.get("pool_age_hours", 72.0)
    age_bonus = 8.0 if pool_age_h <= 24.0 else (5.0 if pool_age_h <= 72.0 else 0.0)
    s_timing = min(100.0, timing_score + age_bonus)

    # 2. 买盘压力与换手率得分
    buy_ratio = item.get("buy_ratio", 50.0)
    vol_mc_ratio = item.get("vol_24h", 0.0) / max(item.get("mc_usd", 1.0), 1.0)
    s_buy = min(100.0, 50.0 + (buy_ratio - 50.0) * 3.2 + min(vol_mc_ratio * 15.0, 22.0))

    # 3. 市值高赔率得分（偏爱 $20万 ~ $600万 的黄金高赔率区间）
    mc_wan = item.get("mc_usd", 0.0) / 10000.0
    if is_meme:
        if 15.0 <= mc_wan <= 300.0:
            s_mc = 95.0
        elif 300.0 < mc_wan <= 700.0:
            s_mc = 85.0
        elif 700.0 < mc_wan <= 1200.0:
            s_mc = 72.0
        else:
            s_mc = 58.0
    else:
        if 50.0 <= mc_wan <= 1200.0:
            s_mc = 94.0
        elif 1200.0 < mc_wan <= 2800.0:
            s_mc = 82.0
        else:
            s_mc = 65.0

    # 4. 赛道与叙事共振得分
    text = f"{item.get('name', '')} {item.get('symbol', '')} {item.get('track', '')}".lower()
    s_track = 70.0
    if any(t.lower() in text for t in approved_tracks):
        s_track += 18.0
    if any(k.lower() in text for k in hot_keywords):
        s_track += 12.0
    s_track = min(100.0, s_track)

    # 5. 池子流动性与交易笔数健康度
    liq_mc_ratio = item.get("liq_usd", 0.0) / max(item.get("mc_usd", 1.0), 1.0)
    tx_count = item.get("buys_24h", 0) + item.get("sells_24h", 0)
    s_fund = 65.0
    if 0.08 <= liq_mc_ratio <= 0.65:
        s_fund += 20.0
    if tx_count >= 300:
        s_fund += 15.0
    s_fund = min(100.0, s_fund)

    total = (
        s_timing * w_timing
        + s_buy * w_buy
        + s_mc * w_mc
        + s_track * w_track
        + s_fund * w_fund
    )
    return round(min(max(total, 0.0), 100.0), 1)


def fetch_tavily_context(symbol: str, name: str, track: str) -> str:
    """若配置了 Tavily API Key，为进入终审的标的补充最新情报"""
    if not TAVILY_API_KEY:
        return f"所属赛道: {track}，链上早期买盘持续流入"
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": f"{name} {symbol} crypto token {track}",
                "search_depth": "basic",
                "max_results": 2,
            },
            timeout=8,
        )
        if resp.status_code == 200:
            results = resp.json().get("results", []) or []
            snippets = [r.get("title", "") for r in results if r.get("title")]
            if snippets:
                return " | ".join(snippets)[:120]
    except Exception:
        pass
    return f"所属赛道: {track}，链上早期资金共振"


def send_feishu_card(projects: list, evo_state: dict):
    """推送 V6.0 极早期狙击战报卡片至飞书群"""
    if not FEISHU_URL or not projects:
        return

    gen = evo_state.get("generation", 1)
    guard = evo_state.get("guardrails", {})
    lines = [
        f"🧬 **进化代数**: Gen #{gen} | **防追高红线**: 24h ≤ +{guard.get('max_24h_pump_limit', 68)}% | **Meme市值上限**: ${guard.get('max_meme_mc_wan', 1500)}万\n---"
    ]
    for idx, p in enumerate(projects, 1):
        lines.append(
            f"**{idx}. {p['name']} ({p['symbol']})** | `{p['project_type']}` | 评分: **{p['score']}**\n"
            f"• **买点阶段**: {p.get('entry_timing', '🟢 早期启动')} | **上线时长**: {p.get('age_label', '新盘')}\n"
            f"• **市值**: ${p['mc_wan']:.1f}万 | **24h量**: ${p['vol_wan']:.1f}万 | **流动性**: ${p['liq_wan']:.1f}万\n"
            f"• **动量**: 1h `{p['chg_1h']:+.1f}%` / 24h `{p['chg_24h']:+.1f}%` | **买盘占比**: `{p['buy_ratio']:.1f}%`\n"
            f"• **催化剂**: {p.get('catalyst', '')}\n"
            f"• **CIO简评**: {p.get('report', '')}\n"
            f"• [点击查看 DEX 实时K线与合约]({p.get('dex_url', '#')})\n"
        )

    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"🎯 V6.0 极早期高赔率 Alpha 狙击战报 ({len(projects)}个标的)",
                },
                "template": "turquoise",
            },
            "elements": [
                {"tag": "markdown", "content": "\n".join(lines)},
            ],
        },
    }
    try:
        requests.post(FEISHU_URL, json=payload, timeout=10)
    except Exception as e:
        print(f"⚠️ 飞书群卡片推送异常: {e}")


def run_job2():
    print("🚀 [Job 2 V6.0] 启动极早期点火狙击引擎 + 动态进化风控闸门...")
    db = FeishuDB()
    local_db = load_local_db()
    evo_state = get_active_evolution_state(local_db)
    guardrails = evo_state.get("guardrails", DEFAULT_EVOLUTION_STATE["guardrails"])

    # 兼容新旧 FeishuDB.get_strategy_weights 签名
    try:
        weights = db.get_strategy_weights(evo_state)
    except TypeError:
        weights = db.get_strategy_weights()
        if isinstance(evo_state.get("weights"), dict):
            weights = evo_state["weights"]

    print(
        f"🧬 当前策略代数: Gen #{evo_state.get('generation', 1)} | "
        f"Meme市值上限: ${guardrails.get('max_meme_mc_wan')}万 | "
        f"价值市值上限: ${guardrails.get('max_narrative_mc_wan')}万 | "
        f"24h防追高上限: +{guardrails.get('max_24h_pump_limit')}% | "
        f"最低买盘占比: {guardrails.get('min_buy_ratio_pct')}%"
    )

    approved_tracks = db.get_approved_tracks()
    if not approved_tracks:
        approved_tracks = [
            t.get("name", "")
            for t in local_db.get("tracks", [])
            if isinstance(t, dict) and t.get("name")
        ]

    hot_keywords = [
        k.get("keyword", "")
        for k in local_db.get("hot_keywords", [])
        if isinstance(k, dict) and k.get("keyword")
    ]

    # 1. 多源并发嗅探：重点抓取刚开盘新池子(new_pools) + 底部放量池(trending_pools) + 早期异动池
    gecko_new = scan_gecko_pools("new_pools", pages=2)
    gecko_trending = scan_gecko_pools("trending_pools", pages=1)
    dex_boosted = scan_dexscreener_early_gems(hot_keywords)

    raw_candidates = gecko_new + gecko_trending + dex_boosted
    print(f"📡 链上原始扫描完成: 新池子 {len(gecko_new)} 个 | 异动池 {len(gecko_trending)} 个 | 叙事搜索 {len(dex_boosted)} 个")

    # 2. 去重与严格风控过滤（彻底解决大市值、高位接盘、假死盘问题）
    dedup_map = {}
    for item in raw_candidates:
        sym = item.get("symbol", "").upper().strip()
        contract = item.get("contract", "").strip()
        if not sym or len(sym) < 2 or not contract:
            continue
        key = f"{item.get('chain', '')}_{contract.lower()}"
        if key not in dedup_map or item.get("vol_24h", 0) > dedup_map[key].get("vol_24h", 0):
            dedup_map[key] = item

    max_meme_mc_usd = float(guardrails.get("max_meme_mc_wan", 1500.0)) * 10000.0
    max_narr_mc_usd = float(guardrails.get("max_narrative_mc_wan", 5000.0)) * 10000.0
    min_score_threshold = float(guardrails.get("min_score_threshold", 68.0))

    existing_projects = local_db.get("projects", []) or []
    existing_symbols = {str(p.get("symbol", "")).upper() for p in existing_projects[:20]}

    qualified = []
    reject_stats = {"blacklist": 0, "mc_liq": 0, "entry_timing": 0}

    for item in dedup_map.values():
        sym_lower = item["symbol"].lower()
        clean_sym = re.sub(r"[^a-z0-9]", "", sym_lower)
        if sym_lower in MEGA_CAP_BLACKLIST or clean_sym in MEGA_CAP_BLACKLIST:
            reject_stats["blacklist"] += 1
            continue
        if item["symbol"] in existing_symbols:
            continue

        p_type, track = classify_project_and_track(item, approved_tracks, hot_keywords)
        is_meme = "Meme" in p_type
        mc_usd = item.get("mc_usd", 0.0)
        liq_usd = item.get("liq_usd", 0.0)
        vol_24h = item.get("vol_24h", 0.0)

        # 市值与流动性硬性门槛（拒绝归零貔貅盘，同时严禁大市值低赔率标的）
        min_liq = 18000.0 if is_meme else 45000.0
        max_mc = max_meme_mc_usd if is_meme else max_narr_mc_usd
        if mc_usd < 80000.0 or mc_usd > max_mc or liq_usd < min_liq or vol_24h < 25000.0:
            reject_stats["mc_liq"] += 1
            continue

        # 买点阶段与防追高硬性考核
        entry_ok, entry_timing, timing_score, reject_reason = assess_entry_position(
            item, guardrails, is_meme
        )
        if not entry_ok:
            reject_stats["entry_timing"] += 1
            continue

        item["project_type"] = p_type
        item["track"] = track
        item["entry_timing"] = entry_timing
        item["timing_score"] = timing_score
        item["mc_wan"] = round(mc_usd / 10000.0, 2)
        item["liq_wan"] = round(liq_usd / 10000.0, 2)
        item["vol_wan"] = round(vol_24h / 10000.0, 2)

        q_score = calculate_quant_score(
            item, timing_score, weights, is_meme, approved_tracks, hot_keywords
        )
        item["quant_score"] = q_score
        qualified.append(item)

    qualified.sort(key=lambda x: x["quant_score"], reverse=True)
    print(
        f"🛡️ 早期风控漏斗过滤完成: 拦截主流老币 {reject_stats['blacklist']} 个 | "
        f"拦截市值/流动性不符 {reject_stats['mc_liq']} 个 | "
        f"拦截高位追涨/走弱盘 {reject_stats['entry_timing']} 个 | "
        f"晋级 CIO 终审 {len(qualified[:5])} 个"
    )

    # 3. 取量化评分最高的前 5 个极早期标的送入进化感知型 CIO 终审
    shortlist = qualified[:5]
    final_picks = []
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    for p_data in shortlist:
        p_data["news_context"] = fetch_tavily_context(
            p_data["symbol"], p_data["name"], p_data["track"]
        )
        # 兼容新旧 multi_agent_evaluate 参数与返回值个数
        try:
            eval_res = multi_agent_evaluate(p_data, evo_state)
        except TypeError:
            eval_res = multi_agent_evaluate(p_data)

        if isinstance(eval_res, (tuple, list)):
            if len(eval_res) >= 6:
                ai_score, report, verified_type, verified_track, catalyst, ai_timing = eval_res[:6]
            elif len(eval_res) == 5:
                ai_score, report, verified_type, verified_track, catalyst = eval_res
                ai_timing = p_data.get("entry_timing", "🟢 早期启动")
            elif len(eval_res) == 4:
                ai_score, report, verified_type, verified_track = eval_res
                catalyst = f"24h买盘占比{p_data.get('buy_ratio', 50):.0f}%，早期资金异动"
                ai_timing = p_data.get("entry_timing", "🟢 早期启动")
            else:
                ai_score, report, verified_type, verified_track, catalyst, ai_timing = (
                    72.0,
                    "量化与风控模型通过",
                    p_data.get("project_type", "🌪️ 高波Meme"),
                    p_data.get("track", "Meme"),
                    "链上早期资金点火",
                    p_data.get("entry_timing", "🟢 早期启动"),
                )
        else:
            continue

        # 融合量化分 (45%) + CIO 终审分 (55%)
        final_score = round(p_data["quant_score"] * 0.45 + float(ai_score) * 0.55, 1)

        # CIO 一票否决或总分未达标则淘汰
        if float(ai_score) < 62.0 or final_score < min_score_threshold:
            print(
                f"   ❌ [CIO 否决] {p_data['symbol']} (量化:{p_data['quant_score']} / AI:{ai_score} -> 总分:{final_score}): {report[:45]}..."
            )
            continue

        p_data["score"] = final_score
        p_data["report"] = report
        p_data["project_type"] = verified_type
        p_data["track"] = verified_track
        p_data["catalyst"] = catalyst
        p_data["entry_timing"] = ai_timing or p_data["entry_timing"]
        p_data["found_at"] = now_str
        p_data["recommended_price"] = p_data["price"]
        p_data["live_price"] = p_data["price"]
        p_data["live_roi_pct"] = 0.0

        final_picks.append(p_data)
        db.save_alpha_project(p_data)
        print(
            f"   ✅ [入选极早期 Alpha] {p_data['name']} ({p_data['symbol']}) | "
            f"{p_data['entry_timing']} | 市值:${p_data['mc_wan']}万 | 24h:{p_data['chg_24h']:+.1f}% | 综合分:{final_score}"
        )

    # 4. 更新本地数据库并刷新 GitHub Pages 看板
    merged_projects = final_picks + existing_projects
    dedup_projects = []
    seen_sym = set()
    for p in merged_projects:
        s = str(p.get("symbol", "")).upper()
        if s and s not in seen_sym:
            seen_sym.add(s)
            dedup_projects.append(p)

    local_db["updated_at"] = now_str
    local_db["projects"] = dedup_projects[:36]
    local_db["evolution_state"] = evo_state

    os.makedirs(os.path.dirname(LOCAL_DB_PATH), exist_ok=True)
    with open(LOCAL_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(local_db, f, ensure_ascii=False, indent=2)

    build_dashboard()
    if final_picks:
        send_feishu_card(final_picks, evo_state)
    else:
        print("ℹ️ 本轮未发现同时满足『极早期 + 低市值 + 安全买点』的高标准标的，宁缺毋滥。")


if __name__ == "__main__":
    run_job2()
