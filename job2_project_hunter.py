from concurrent.futures import ThreadPoolExecutor
import datetime
import json
import os
import re
import time
import requests
from config import (
    COINGECKO_API_KEY,
    FEISHU_WEBHOOK_URL,
    TAVILY_API_KEY,
    DEFAULT_EVOLUTION_STATE,
)
from feishu_db import FeishuDB
from llm_engine import multi_agent_evaluate
from logger import get_logger
from models import normalize_project, project_unique_key
from notifier import build_dashboard

log = get_logger("job2_project_hunter")
_SESSION = requests.Session()
LOCAL_DB_PATH = "docs/alpha_db.json"

GOPLUS_CHAIN_IDS = {
    "eth": "1",
    "ethereum": "1",
    "bsc": "56",
    "polygon": "137",
    "arbitrum": "42161",
    "base": "8453",
    "optimism": "10",
    "avax": "43114",
}

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
            log.warning("读取 %s 异常: %s", LOCAL_DB_PATH, e)
    return {
        "updated_at": "",
        "hot_keywords": [],
        "vc_And_news": [],
        "tracks": [],
        "projects": [],
        "evolution_state": DEFAULT_EVOLUTION_STATE,
    }


def get_active_evolution_state(local_db: dict) -> dict:
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
    if not created_at_val:
        return 72.0
    now_ts = time.time()
    try:
        if isinstance(created_at_val, (int, float)):
            ts = float(created_at_val)
            if ts > 1e11:
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
    results = []
    headers = {"Accept": "application/json;version=20230302"}

    for page in range(1, pages + 1):
        url = f"https://api.geckoterminal.com/api/v2/networks/{endpoint_type}?include=base_token&page={page}"
        try:
            resp = _SESSION.get(url, headers=headers, timeout=12)
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
                base_id = rels.get("base_token", {}).get("data", {}).get("id", "")
                net_id = rels.get("network", {}).get("data", {}).get("id", "")
                if not net_id and "_" in base_id:
                    net_id = base_id.split("_")[0]

                meta = token_meta.get(base_id, {})
                pool_name = str(attrs.get("name", ""))
                symbol = meta.get("symbol") or (pool_name.split("/")[0].strip() if "/" in pool_name else pool_name)
                name = meta.get("name") or symbol
                contract = meta.get("address") or (base_id.split("_", 1)[1] if "_" in base_id else "")

                price_usd = float(attrs.get("base_token_price_usd") or 0.0)
                mc_usd = float(attrs.get("market_cap_usd") or attrs.get("fdv_usd") or 0.0)
                fdv_usd = float(attrs.get("fdv_usd") or mc_usd or 0.0)
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
                mc_fdv_ratio = round((mc_usd / fdv_usd) * 100.0, 1) if fdv_usd > 0 and mc_usd > 0 else 0.0

                results.append(
                    {
                        "name": name,
                        "symbol": symbol.upper(),
                        "chain": (net_id or "solana").lower(),
                        "contract": contract,
                        "price": price_usd,
                        "mc_usd": mc_usd,
                        "mc_fdv_ratio": mc_fdv_ratio,
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
            log.warning("GeckoTerminal (%s p%d) 扫描异常: %s", endpoint_type, page, e)
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
        fdv_usd = float(pair.get("fdv") or mc_usd or 0.0)
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
        mc_fdv_ratio = round((mc_usd / fdv_usd) * 100.0, 1) if fdv_usd > 0 and mc_usd > 0 else 0.0

        return {
            "name": name,
            "symbol": symbol,
            "chain": chain,
            "contract": contract,
            "price": price,
            "mc_usd": mc_usd,
            "mc_fdv_ratio": mc_fdv_ratio,
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


def scan_dexscreener_early_gems(keywords: list) -> list:
    results = []
    seen_pairs = set()

    try:
        boost_resp = _SESSION.get("https://api.dexscreener.com/token-boosts/top/v1", timeout=10)
        if boost_resp.status_code == 200:
            boosts = boost_resp.json()
            if isinstance(boosts, list):
                addrs = [b.get("tokenAddress") for b in boosts[:15] if b.get("tokenAddress")]
                if addrs:
                    chunk = ",".join(addrs[:10])
                    p_resp = _SESSION.get(f"https://api.dexscreener.com/latest/dex/tokens/{chunk}", timeout=10)
                    if p_resp.status_code == 200:
                        for pair in (p_resp.json().get("pairs") or [])[:25]:
                            parsed = _parse_dexscreener_pair(pair)
                            if parsed:
                                k = project_unique_key(parsed)
                                if k not in seen_pairs:
                                    seen_pairs.add(k)
                                    results.append(parsed)
    except Exception as e:
        log.warning("DexScreener Boosts 扫描异常: %s", e)

    search_terms = [k for k in keywords[:5] if k] + ["ai agent", "desci", "rwa"]

    def _search_kw(kw):
        found = []
        try:
            url = f"https://api.dexscreener.com/latest/dex/search?q={requests.utils.quote(str(kw))}"
            resp = _SESSION.get(url, timeout=10)
            if resp.status_code == 200:
                for pair in (resp.json().get("pairs") or [])[:12]:
                    parsed = _parse_dexscreener_pair(pair, matched_kw=str(kw))
                    if parsed:
                        found.append(parsed)
        except Exception:
            pass
        return found

    with ThreadPoolExecutor(max_workers=4) as pool:
        for batch in pool.map(_search_kw, search_terms[:6]):
            for parsed in batch:
                k = project_unique_key(parsed)
                if k not in seen_pairs:
                    seen_pairs.add(k)
                    results.append(parsed)

    return results


def classify_project_and_track(item: dict, approved_tracks: list, hot_keywords: list) -> tuple:
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
    """V7.0 全周期买点识别与防追高/防刷单闸门"""
    chg_1h = item.get("chg_1h", 0.0)
    chg_6h = item.get("chg_6h", 0.0)
    chg_24h = item.get("chg_24h", 0.0)
    buy_ratio = item.get("buy_ratio", 50.0)
    mc_usd = item.get("mc_usd", 0.0)
    vol_24h = item.get("vol_24h", 0.0)
    vol_1h = item.get("vol_1h", 0.0)
    tx_count = int(item.get("buys_24h", 0)) + int(item.get("sells_24h", 0))
    pool_age_h = item.get("pool_age_hours", 72.0)

    max_24h_pump = float(guardrails.get("max_24h_pump_limit", 68.0))
    sweet_24h_max = float(guardrails.get("sweet_spot_24h_max", 38.0))
    min_buy_ratio = float(guardrails.get("min_buy_ratio_pct", 53.5))

    if tx_count >= 200 and vol_24h > 0 and (vol_24h / tx_count) < 15.0:
        return False, "", 0.0, f"疑似微额刷单(均笔${vol_24h / tx_count:.1f} < $15)"
    if pool_age_h > 2.0 and vol_1h <= 0 and vol_24h > 0:
        return False, "", 0.0, "近1h无有效成交量(流动性停滞)"

    if buy_ratio < min_buy_ratio:
        return False, "", 0.0, f"买盘占比偏弱({buy_ratio:.1f}% < {min_buy_ratio}%)"

    if chg_24h > 25.0 and chg_1h < -4.0:
        return False, "", 0.0, f"高位放量派发迹象(24h+{chg_24h:.1f}%, 1h{chg_1h:.1f}%)"

    is_ultra_early_ignition = (
        pool_age_h <= 24.0
        and mc_usd <= 3000000
        and buy_ratio >= 58.0
        and 1.0 <= chg_1h <= 28.0
        and chg_24h <= (max_24h_pump * 1.35)
    )
    if chg_24h > max_24h_pump and not is_ultra_early_ignition:
        return False, "", 0.0, f"24h涨幅过高(+{chg_24h:.1f}% > +{max_24h_pump:.0f}%)，拒绝追高接盘"

    if chg_1h > 35.0:
        return False, "", 0.0, f"1h短线急拉过猛(+{chg_1h:.1f}%)，防冲高回落"

    if chg_24h < -22.0 or (chg_6h < -12.0 and chg_1h < 0):
        return False, "", 0.0, f"趋势走弱阴跌(24h {chg_24h:.1f}%)"

    if pool_age_h <= 48.0 and -5.0 <= chg_24h <= sweet_24h_max and chg_1h >= 0.8 and buy_ratio >= 55.0:
        return True, "🟢 新币极早期点火窗口", 95.0, ""

    if -2.0 <= chg_24h <= 25.0 and 1.2 <= chg_1h <= 18.0 and buy_ratio >= 54.5:
        return True, "🟢 底部刚启动首阳买点", 92.0, ""

    if -12.0 <= chg_24h <= 30.0 and -10.0 <= chg_6h <= 2.0 and 0.5 <= chg_1h <= 12.0 and buy_ratio >= 55.0:
        return True, "💎 缩量回调企稳黄金坑", 88.0, ""

    if 0.0 <= chg_24h <= sweet_24h_max and 0.5 <= chg_1h <= 22.0:
        return True, "🚀 右侧温和放量突破期", 84.0, ""

    if is_ultra_early_ignition:
        return True, "🔥 首日新盘强势点火期", 82.0, ""

    if chg_1h >= 0.0 and chg_24h <= max_24h_pump:
        return True, "🟢 早期右侧温和跟进", 74.0, ""

    return False, "", 0.0, "未出现明确早期启动或企稳信号"


def check_token_security(chain: str, contract: str) -> tuple:
    if not contract:
        return True, "无合约信息"

    chain_lower = chain.lower().strip()
    if chain_lower == "solana":
        try:
            resp = _SESSION.get(
                f"https://api.rugcheck.xyz/v1/tokens/{contract}/report/summary",
                timeout=6,
            )
            if resp.status_code == 200:
                data = resp.json() or {}
                for r in (data.get("risks") or []):
                    level = str(r.get("level", "")).lower()
                    name = str(r.get("name", ""))
                    if level in ("danger", "critical") or "honeypot" in name.lower():
                        return False, f"RugCheck高危: {name}"
                return True, "RugCheck安全通过"
        except Exception:
            return True, "RugCheck超时放行"

    chain_id = GOPLUS_CHAIN_IDS.get(chain_lower)
    if chain_id:
        try:
            resp = _SESSION.get(
                f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}",
                params={"contract_addresses": contract.lower()},
                timeout=6,
            )
            if resp.status_code == 200:
                info = (resp.json().get("result") or {}).get(contract.lower()) or {}
                if info.get("is_honeypot") == "1":
                    return False, "GoPlus判定为貔貅盘(无法卖出)"
                if info.get("cannot_sell_all") == "1":
                    return False, "GoPlus检测到限制全部卖出"
                sell_tax = float(info.get("sell_tax") or 0)
                buy_tax = float(info.get("buy_tax") or 0)
                if sell_tax > 0.08 or buy_tax > 0.08:
                    return False, f"买卖税率过高(买{buy_tax*100:.0f}%/卖{sell_tax*100:.0f}%)"
                return True, "GoPlus安全通过"
        except Exception:
            return True, "GoPlus超时放行"

    return True, "未覆盖链放行"


def enrich_value_fundamentals(p_data: dict, vc_entities: list) -> dict:
    """
    V7.0 价值挖掘基本面穿透：
    补充 CoinGecko 流通率/距ATH回撤/GitHub月提交数，并匹配一级市场 VC 融资实体。
    """
    headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    if COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = COINGECKO_API_KEY

    name_lower = p_data.get("name", "").lower()
    sym_lower = p_data.get("symbol", "").lower()
    vc_hits = [vc for vc in vc_entities if vc and (vc in name_lower or name_lower in vc)]
    p_data["vc_hits"] = vc_hits[:3]

    # 仅对较大市值或叙事价值标的尝试 CoinGecko 基本面穿透，避免限流
    if p_data.get("mc_usd", 0) >= 800000:
        try:
            s_resp = _SESSION.get(
                "https://api.coingecko.com/api/v3/search",
                params={"query": p_data.get("symbol")},
                headers=headers,
                timeout=6,
            )
            if s_resp.status_code == 200:
                coins = s_resp.json().get("coins") or []
                match = next((c for c in coins if str(c.get("symbol", "")).lower() == sym_lower), None)
                if match and match.get("id"):
                    cid = match["id"]
                    p_data["coingecko_id"] = cid
                    c_resp = _SESSION.get(
                        f"https://api.coingecko.com/api/v3/coins/{cid}",
                        params={"localization": "false", "tickers": "false", "community_data": "false"},
                        headers=headers,
                        timeout=6,
                    )
                    if c_resp.status_code == 200:
                        cdata = c_resp.json() or {}
                        mdata = cdata.get("market_data") or {}
                        mc = float((mdata.get("market_cap") or {}).get("usd") or 0)
                        fdv = float((mdata.get("fully_diluted_valuation") or {}).get("usd") or 0)
                        if mc > 0 and fdv > 0:
                            p_data["mc_fdv_ratio"] = round((mc / fdv) * 100.0, 1)
                        ath_chg = (mdata.get("ath_change_percentage") or {}).get("usd")
                        if ath_chg is not None:
                            p_data["ath_drop"] = round(float(ath_chg), 1)
                        dev = cdata.get("developer_data") or {}
                        p_data["commits_4w"] = int(dev.get("commit_count_4_weeks") or 0)
        except Exception:
            pass
    return p_data


def cross_validate_signal(
    p_data: dict,
    approved_tracks: list,
    hot_keywords: list,
    trending_symbols: list,
    sec_ok: bool,
    news_ctx: str,
) -> tuple:
    """
    V7.0 多维全景交叉验证引擎：
    从 链上量价 / 市场热搜 / 赛道与VC资金面 / 合约安全 / 外部新闻情报 5 个维度交叉验真。
    返回: (cv_score: float, cv_signals: list, cv_confidence: str)
    """
    signals = []
    score = 45.0

    # 1. 链上量价与买盘共振
    if p_data.get("buy_ratio", 50.0) >= 54.0 and p_data.get("vol_24h", 0) >= 50000:
        signals.append("链上真实放量买盘")
        score += 15.0

    # 2. 全网热搜或 DexScreener Boost 共振
    sym = p_data.get("symbol", "").upper()
    if sym in trending_symbols or p_data.get("source") == "DexScreener":
        signals.append("多平台热点共振")
        score += 12.0

    # 3. 赛道或一级 VC 资金面命中
    text = f"{p_data.get('name', '')} {sym} {p_data.get('track', '')}".lower()
    if p_data.get("vc_hits") or any(t.lower() in text for t in approved_tracks) or any(k.lower() in text for k in hot_keywords):
        signals.append("赛道/VC资金面对齐")
        score += 12.0

    # 4. 合约安全审计通过
    if sec_ok and "通过" in str(p_data.get("security_status", "")):
        signals.append("合约安全审计通过")
        score += 10.0

    # 5. 外部舆情/新闻催化或基本面开发活跃
    if (news_ctx and "|" in news_ctx) or int(p_data.get("commits_4w") or 0) >= 10:
        signals.append("外部催化/开发活跃")
        score += 8.0

    score = round(min(100.0, score), 1)
    if len(signals) >= 3:
        conf = f"高置信度({len(signals)}维交叉)"
    elif len(signals) == 2:
        conf = "中置信度(2维交叉)"
    else:
        conf = "单源观察"

    return score, signals, conf


def calculate_quant_score(
    item: dict,
    timing_score: float,
    weights: dict,
    is_meme: bool,
    approved_tracks: list,
    hot_keywords: list,
) -> float:
    w_timing = float(weights.get("early_timing", 0.30))
    w_buy = float(weights.get("buy_pressure", 0.25))
    w_mc = float(weights.get("mc_odds", 0.20))
    w_track = float(weights.get("track_heat", 0.15))
    w_fund = float(weights.get("fundamentals", 0.10))

    pool_age_h = item.get("pool_age_hours", 72.0)
    age_bonus = 8.0 if pool_age_h <= 24.0 else (5.0 if pool_age_h <= 72.0 else 0.0)
    s_timing = min(100.0, timing_score + age_bonus)

    buy_ratio = item.get("buy_ratio", 50.0)
    vol_mc_ratio = item.get("vol_24h", 0.0) / max(item.get("mc_usd", 1.0), 1.0)
    s_buy = min(100.0, 50.0 + (buy_ratio - 50.0) * 3.2 + min(vol_mc_ratio * 15.0, 22.0))

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

    text = f"{item.get('name', '')} {item.get('symbol', '')} {item.get('track', '')}".lower()
    s_track = 70.0
    if any(t.lower() in text for t in approved_tracks):
        s_track += 18.0
    if any(k.lower() in text for k in hot_keywords):
        s_track += 12.0
    s_track = min(100.0, s_track)

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
    if not TAVILY_API_KEY:
        return f"所属赛道: {track}，链上早期买盘持续流入"
    try:
        resp = _SESSION.post(
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
    if not FEISHU_WEBHOOK_URL or not projects:
        return

    gen = evo_state.get("generation", 1)
    guard = evo_state.get("guardrails", {})
    lines = [
        f"🧬 **进化代数**: Gen #{gen} | **胜率/盈亏比**: {evo_state.get('win_rate_pct', 0)}% / {evo_state.get('payoff_ratio', 1.0)} | **防追高红线**: 24h ≤ +{guard.get('max_24h_pump_limit', 68)}%\n---"
    ]
    for idx, p in enumerate(projects, 1):
        lines.append(
            f"**{idx}. {p['name']} ({p['symbol']})** | `{p['project_type']}` | 评分: **{p['score']}** | `{p.get('cv_confidence', '')}`\n"
            f"• **买点阶段**: {p.get('entry_timing', '🟢 早期启动')} | **仓位建议**: {p.get('position_tier', '标准建仓')}\n"
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
                    "content": f"🎯 V7.0 全周期 Alpha 狙击战报 ({len(projects)}个标的)",
                },
                "template": "turquoise",
            },
            "elements": [
                {"tag": "markdown", "content": "\n".join(lines)},
            ],
        },
    }
    try:
        _SESSION.post(FEISHU_WEBHOOK_URL, json=payload, timeout=10)
    except Exception as e:
        log.warning("飞书群卡片推送异常: %s", e)


def run_job2():
    log.info("[Job 2 V7.0] 启动全周期 Alpha 捕获 + 多维交叉验证 + 多空辩论投委会...")
    db = FeishuDB()
    local_db = load_local_db()
    evo_state = get_active_evolution_state(local_db)
    guardrails = evo_state.get("guardrails", DEFAULT_EVOLUTION_STATE["guardrails"])

    try:
        weights = db.get_strategy_weights(evo_state)
    except TypeError:
        weights = db.get_strategy_weights()
        if isinstance(evo_state.get("weights"), dict):
            weights = evo_state["weights"]

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
    trending_symbols = [str(s).upper() for s in (local_db.get("trending_symbols") or [])]
    vc_entities = [str(v).lower() for v in (local_db.get("vc_entities") or [])]

    with ThreadPoolExecutor(max_workers=3) as pool:
        f_new = pool.submit(scan_gecko_pools, "new_pools", 2)
        f_trend = pool.submit(scan_gecko_pools, "trending_pools", 1)
        f_dex = pool.submit(scan_dexscreener_early_gems, hot_keywords)
        gecko_new = f_new.result()
        gecko_trending = f_trend.result()
        dex_boosted = f_dex.result()

    raw_candidates = gecko_new + gecko_trending + dex_boosted
    log.info(
        "链上原始扫描完成: 新池子 %d 个 | 异动池 %d 个 | 叙事搜索 %d 个",
        len(gecko_new), len(gecko_trending), len(dex_boosted),
    )

    dedup_map = {}
    for item in raw_candidates:
        sym = item.get("symbol", "").upper().strip()
        contract = item.get("contract", "").strip()
        if not sym or len(sym) < 2 or not contract:
            continue
        key = project_unique_key(item)
        if key not in dedup_map or item.get("vol_24h", 0) > dedup_map[key].get("vol_24h", 0):
            dedup_map[key] = item

    max_meme_mc_usd = float(guardrails.get("max_meme_mc_wan", 1500.0)) * 10000.0
    max_narr_mc_usd = float(guardrails.get("max_narrative_mc_wan", 5000.0)) * 10000.0
    min_score_threshold = float(guardrails.get("min_score_threshold", 68.0))

    existing_projects = [normalize_project(p) for p in (local_db.get("projects") or [])]
    existing_keys = {project_unique_key(p) for p in existing_projects[:30]}

    qualified = []
    reject_stats = {"blacklist": 0, "mc_liq": 0, "entry_timing": 0}

    for item in dedup_map.values():
        sym_lower = item["symbol"].lower()
        clean_sym = re.sub(r"[^a-z0-9]", "", sym_lower)
        if sym_lower in MEGA_CAP_BLACKLIST or clean_sym in MEGA_CAP_BLACKLIST:
            reject_stats["blacklist"] += 1
            continue
        if project_unique_key(item) in existing_keys:
            continue

        p_type, track = classify_project_and_track(item, approved_tracks, hot_keywords)
        is_meme = "Meme" in p_type
        mc_usd = item.get("mc_usd", 0.0)
        liq_usd = item.get("liq_usd", 0.0)
        vol_24h = item.get("vol_24h", 0.0)

        min_liq = 18000.0 if is_meme else 45000.0
        max_mc = max_meme_mc_usd if is_meme else max_narr_mc_usd
        if mc_usd < 80000.0 or mc_usd > max_mc or liq_usd < min_liq or vol_24h < 25000.0:
            reject_stats["mc_liq"] += 1
            continue

        entry_ok, entry_timing, timing_score, _ = assess_entry_position(item, guardrails, is_meme)
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
        item["turnover_24h"] = round((vol_24h / max(mc_usd, 1.0)) * 100.0, 1)

        q_score = calculate_quant_score(
            item, timing_score, weights, is_meme, approved_tracks, hot_keywords
        )
        item["quant_score"] = q_score
        qualified.append(item)

    qualified.sort(key=lambda x: x["quant_score"], reverse=True)
    shortlist = qualified[:6]
    final_picks = []
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    def _enrich(p_data):
        sec_ok, sec_msg = check_token_security(p_data["chain"], p_data["contract"])
        news_ctx = fetch_tavily_context(p_data["symbol"], p_data["name"], p_data["track"]) if sec_ok else ""
        if sec_ok:
            enrich_value_fundamentals(p_data, vc_entities)
        return sec_ok, sec_msg, news_ctx

    with ThreadPoolExecutor(max_workers=4) as pool:
        enriched = list(pool.map(_enrich, shortlist))

    for p_data, (sec_ok, sec_msg, news_ctx) in zip(shortlist, enriched):
        if not sec_ok:
            log.info("❌ [合约审计拦截] %s: %s", p_data["symbol"], sec_msg)
            continue

        p_data["security_status"] = sec_msg
        p_data["news_context"] = news_ctx
        cv_score, cv_signals, cv_conf = cross_validate_signal(
            p_data, approved_tracks, hot_keywords, trending_symbols, sec_ok, news_ctx
        )
        p_data["cv_score"] = cv_score
        p_data["cv_signals"] = cv_signals
        p_data["cv_confidence"] = cv_conf

        eval_res = multi_agent_evaluate(p_data, evo_state)
        if isinstance(eval_res, (tuple, list)) and len(eval_res) >= 6:
            ai_score, report, verified_type, verified_track, catalyst, ai_timing = eval_res[:6]
        else:
            continue

        # 融合量化分(35%) + 多维交叉验证(15%) + CIO终审(50%)
        final_score = round(p_data["quant_score"] * 0.35 + cv_score * 0.15 + float(ai_score) * 0.50, 1)

        if float(ai_score) < 62.0 or final_score < min_score_threshold:
            log.info("❌ [CIO 否决] %s (总分:%s): %s...", p_data["symbol"], final_score, report[:45])
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
        p_data["peak_price"] = p_data["price"]
        p_data["live_roi_pct"] = 0.0
        p_data["max_drawdown_pct"] = 0.0

        canonical = normalize_project(p_data)
        final_picks.append(canonical)
        db.save_alpha_project(canonical)
        log.info(
            "✅ [入选 Alpha] %s (%s) | %s | %s | 市值:$%s万 | 综合分:%s",
            canonical["name"], canonical["symbol"], canonical["entry_timing"],
            cv_conf, canonical["mc_wan"], final_score,
        )

    merged_projects = final_picks + existing_projects
    dedup_projects = []
    seen_keys = set()
    for p in merged_projects:
        k = project_unique_key(p)
        if p.get("symbol") and k not in seen_keys:
            seen_keys.add(k)
            dedup_projects.append(p)

    local_db["updated_at"] = now_str
    local_db["projects"] = dedup_projects[:36]
    local_db["evolution_state"] = evo_state

    os.makedirs(os.path.dirname(LOCAL_DB_PATH), exist_ok=True)
    with open(LOCAL_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(local_db, f, ensure_ascii=False, indent=2)

    build_dashboard(
        f"🎯 V7.0 全周期 Alpha 更新 ({len(final_picks)} 个新标的)" if final_picks else "",
        f"本轮入选: {', '.join(p['symbol'] for p in final_picks)}" if final_picks else "",
    )
    if final_picks:
        send_feishu_card(final_picks, evo_state)
    else:
        log.info("本轮未发现同时满足高赔率与交叉验证标准的新标的，宁缺毋滥。")


if __name__ == "__main__":
    run_job2()
