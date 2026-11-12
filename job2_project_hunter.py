# job2_project_hunter.py - V6.0 极早期点火狙击 + 黄金建仓位置过滤 + 进化阈值驱动
import copy
import re
import time
import requests
from datetime import datetime, timezone, timedelta
from config import COINGECKO_API_KEY, TAVILY_API_KEY, DEFAULT_EVOLUTION_STATE
from feishu_db import FeishuDB
from llm_engine import multi_agent_evaluate
import notifier

# 1. 垃圾币/稳定币/包装币黑名单
TOKEN_BLACKLIST = {
    "usdt", "usdc", "dai", "fdusd", "tusd", "usde", "usdd", "frax", "lusd", "pyusd",
    "gusd", "usdp", "eurc", "eurs", "ceur", "sdy", "usd0", "usdb", "deusd", "usr",
    "wbtc", "weth", "wbnb", "wsol", "wmatic", "wavax", "steth", "wsteth", "reth",
    "cbeth", "weeth", "ezeth", "rseth", "sweth", "meth", "msol", "jitosol", "bnsol",
    "cbbtc", "tbtc", "solvbtc", "lbtc", "ebtc", "matic", "fbomb",
}

# 2. 铁律排除：一切大中市值老牌白马与主流币（只抓极早期、小市值、高赔率项目）
MEGA_CAP_BLACKLIST = {
    "bitcoin", "ethereum", "tether", "binancecoin", "solana", "ripple", "usd-coin",
    "cardano", "dogecoin", "tron", "chainlink", "avalanche-2", "toncoin", "shiba-inu",
    "stellar", "polkadot", "sui", "bitcoin-cash", "hedera-hashgraph", "litecoin",
    "near", "uniswap", "pepe", "aptos", "internet-computer", "monero", "pol-ex-matic",
    "ethereum-classic", "dai", "okb", "cronos", "aave", "mantle", "vechain", "render-token",
    "bittensor", "filecoin", "arbitrum", "optimism", "cosmos", "injective-protocol",
    "immutable-x", "fantom", "the-graph", "theta-token", "algorand", "maker", "sei-network",
    "bonk", "floki", "worldcoin-wld", "celestia", "lido-dao", "gala", "flow", "eos",
    "kaspa", "jasmycoin", "fetch-ai", "pendle", "ondo-finance", "jupiter-exchange-solana",
    "stacks", "beam-2", "dogwifcoin", "brett", "popcat", "mog-coin",
}

MEGA_CAP_SYMBOLS = {
    "btc", "eth", "sol", "bnb", "xrp", "ada", "doge", "trx", "link", "avax",
    "ton", "shib", "dot", "near", "uni", "ltc", "bch", "icp", "etc", "apt",
    "sui", "arb", "op", "atom", "fil", "xlm", "hbar", "vet", "aave", "mkr",
    "pepe", "wif", "bonk", "floki", "fet", "render", "tao", "kas", "ondo",
}


def cg_headers():
    headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    if COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = COINGECKO_API_KEY
    return headers


def _calc_pool_age_hours(created_at_val):
    """计算交易池创建至今的小时数，用于精准识别刚发币极早期项目"""
    if not created_at_val:
        return 999.0
    now_utc = datetime.now(timezone.utc)
    try:
        if isinstance(created_at_val, (int, float)):
            # DexScreener 毫秒时间戳
            ts = created_at_val / 1000.0 if created_at_val > 1e11 else float(created_at_val)
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        else:
            # GeckoTerminal ISO 时间字符串，如 "2025-02-20T08:15:30Z"
            s = str(created_at_val).replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
        hours = max((now_utc - dt).total_seconds() / 3600.0, 0.2)
        return round(hours, 1)
    except Exception:
        return 999.0


def _format_age_label(hours):
    if hours <= 0 or hours >= 720:
        return "二级存量标的"
    if hours < 24:
        return f"🔥 新币上线 {hours:.1f}小时"
    return f"⚡ 上线 {hours / 24:.1f}天"


def is_excluded_token(coin_id="", symbol="", name="", market_cap=0, max_mc_usd=50_000_000):
    """排除稳定币、包装币以及超过动态市值上限的大中市值项目"""
    cid = (coin_id or "").lower().strip()
    sym = (symbol or "").lower().strip()
    nm = (name or "").lower().strip()

    if sym in TOKEN_BLACKLIST or sym in MEGA_CAP_SYMBOLS or cid in MEGA_CAP_BLACKLIST:
        return True

    bad_patterns = [
        "wrapped", "staked", "bridged", "peg", "stablecoin", "usd", "eur",
        "treasury", "tokenized", "restaked", "liquid staking",
    ]
    for pat in bad_patterns:
        if pat in nm or pat in cid:
            return True

    if market_cap and market_cap > max_mc_usd:
        return True

    return False


def assess_entry_position(chg_1h, chg_6h, chg_24h, buy_ratio, mc_usd, pool_age_hours, guardrails, is_meme=False):
    """
    【V6.0 核心买点位置与防追高诊断器】
    判断当前标的是否处于『最佳早期进入窗口』，无情拦截『涨幅过高/错过早期窗口/冲高派发』标的！
    返回: (is_valid_entry: bool, position_score: float, position_tag: str)
    """
    max_pump = float(guardrails.get("max_24h_pump_limit", 68.0))
    sweet_max = float(guardrails.get("sweet_spot_24h_max", 38.0))
    min_buy = float(guardrails.get("min_buy_ratio_pct", 53.5))

    # 1. 铁律拦截：冲高回落派发盘（24h 涨了很多，但 1h 明显砸盘且买单占比弱）
    if chg_24h > 30.0 and chg_1h < -4.5:
        return False, 30.0, "🔴 冲高回落派发(已拦截)"

    # 2. 铁律拦截：涨幅过高，错过最佳建仓窗口（防止高位接盘）
    # 例外豁免：刚上线 < 36 小时、市值极小(< $3.5M) 且买盘极强(buy_ratio >= 58%) 且 1h 仍在稳步向上的极早期新金狗
    is_ultra_early_exception = (
        is_meme and pool_age_hours <= 36.0 and mc_usd <= 3_500_000 and buy_ratio >= 58.0 and 0 < chg_1h <= 30.0
    )
    if chg_24h > max_pump and not is_ultra_early_exception:
        return False, 40.0, "🔴 涨幅过高错过窗口(已拦截)"
    if chg_24h > max_pump * 1.45:
        return False, 35.0, "🔴 极端暴涨高位风险(已拦截)"

    # 3. 铁律拦截：阴跌无买盘承接
    if chg_24h < -15.0 or (chg_1h < -3.0 and buy_ratio < 49.0):
        return False, 40.0, "🔴 空头砸盘无承接(已拦截)"

    # 4. 黄金建仓窗口评级与打分
    if pool_age_hours <= 72.0 and -2.0 <= chg_24h <= sweet_max and chg_1h >= 0.5 and buy_ratio >= min_buy:
        return True, 96.0, "🟢 新币极早期点火窗口"

    if -5.0 <= chg_24h <= 22.0 and 1.0 <= chg_1h <= 18.0 and buy_ratio >= min_buy:
        return True, 94.0, "🟢 底部刚启动第1根阳线"

    if 22.0 < chg_24h <= sweet_max and chg_1h >= 0.0 and buy_ratio >= 51.5:
        return True, 88.0, "🚀 右侧温和放量突破期"

    if sweet_max < chg_24h <= max_pump and chg_1h > 0 and buy_ratio >= min_buy:
        return True, 76.0, "⚡ 主升浪加速初期(轻仓)"

    if -10.0 <= chg_24h < -2.0 and chg_1h >= 0.5 and buy_ratio >= 52.0:
        return True, 86.0, "💎 缩量回调企稳黄金坑"

    return True, 70.0, "🟡 早期震荡蓄势期"


# ==============================================================================
# 引擎 1：链上极早期新池 + 热门金狗狙击 (New Pools + Trending Pools + Boosts)
# ==============================================================================
def fetch_onchain_meme_candidates(guardrails):
    """专门从 GeckoTerminal 新创建池(new_pools)、热门池和 DexScreener 捕捉市值 $15万 ~ $1500万 的极早期标的"""
    candidates = []
    seen_symbols = set()
    max_meme_mc_usd = float(guardrails.get("max_meme_mc_wan", 1500.0)) * 10000.0
    min_buy_ratio = float(guardrails.get("min_buy_ratio_pct", 53.5))

    # 1.1 同时扫描 GeckoTerminal【最新开盘池 new_pools】与【早期异动池 trending_pools】
    endpoints = [
        ("https://api.geckoterminal.com/api/v2/networks/new_pools?include=base_token&page=1", "新池极早期首发"),
        ("https://api.geckoterminal.com/api/v2/networks/trending_pools?include=base_token&page=1", "链上早期点火池"),
    ]
    for url, source_tag in endpoints:
        try:
            resp = requests.get(
                url,
                headers={"Accept": "application/json;version=20230302", "User-Agent": "Mozilla/5.0"},
                timeout=15,
            )
            if resp.status_code != 200:
                continue
            payload = resp.json()
            pools = payload.get("data", [])
            included = {item["id"]: item.get("attributes", {}) for item in payload.get("included", [])}

            for pool in pools:
                attrs = pool.get("attributes", {})
                rel_token_id = (
                    pool.get("relationships", {})
                    .get("base_token", {})
                    .get("data", {})
                    .get("id", "")
                )
                token_meta = included.get(rel_token_id, {})

                chain = rel_token_id.split("_")[0].upper() if "_" in rel_token_id else "ONCHAIN"
                contract_addr = rel_token_id.split("_", 1)[1] if "_" in rel_token_id else ""

                pool_name = attrs.get("name", "")
                symbol = (token_meta.get("symbol") or pool_name.split("/")[0]).strip().upper()
                name = token_meta.get("name") or symbol
                cg_id = token_meta.get("coingecko_coin_id") or ""

                if not symbol or symbol.lower() in seen_symbols:
                    continue

                price = float(attrs.get("base_token_price_usd") or 0)
                liq_usd = float(attrs.get("reserve_in_usd") or 0)
                fdv_usd = float(attrs.get("fdv_usd") or 0)
                mc_usd = float(attrs.get("market_cap_usd") or fdv_usd or (liq_usd * 5) or 0)
                pool_age_h = _calc_pool_age_hours(attrs.get("pool_created_at"))

                if is_excluded_token(cg_id, symbol, name, mc_usd, max_mc_usd=max_meme_mc_usd):
                    continue

                # 极早期市值黄金区间：$15万 ~ $1500万（池子流动性 >= $28,000 防假池）
                if liq_usd < 28_000 or mc_usd < 150_000 or mc_usd > max_meme_mc_usd:
                    continue

                vol_24h = float((attrs.get("volume_usd") or {}).get("h24") or 0)
                vol_6h = float((attrs.get("volume_usd") or {}).get("h6") or 0)
                eff_vol = max(vol_24h, vol_6h * 2.5)

                chg_1h = float((attrs.get("price_change_percentage") or {}).get("h1") or 0)
                chg_6h = float((attrs.get("price_change_percentage") or {}).get("h6") or 0)
                chg_24h = float((attrs.get("price_change_percentage") or {}).get("h24") or 0)

                txns_24h = (attrs.get("transactions") or {}).get("h24") or {}
                txns_1h = (attrs.get("transactions") or {}).get("h1") or {}
                buys_24h = int(txns_24h.get("buys") or 0)
                sells_24h = int(txns_24h.get("sells") or 0)
                buys_1h = int(txns_1h.get("buys") or 0)
                sells_1h = int(txns_1h.get("sells") or 0)

                total_txns = buys_24h + sells_24h
                buy_ratio_24h = round((buys_24h / total_txns) * 100, 1) if total_txns > 0 else 50.0
                buy_ratio_1h = round((buys_1h / (buys_1h + sells_1h)) * 100, 1) if (buys_1h + sells_1h) > 10 else buy_ratio_24h
                effective_buy_ratio = round(buy_ratio_1h * 0.55 + buy_ratio_24h * 0.45, 1)

                if eff_vol < 80_000 or total_txns < 90 or effective_buy_ratio < (min_buy_ratio - 2.0):
                    continue

                ok_entry, pos_score, pos_tag = assess_entry_position(
                    chg_1h, chg_6h, chg_24h, effective_buy_ratio, mc_usd, pool_age_h, guardrails, is_meme=True
                )
                if not ok_entry:
                    continue

                seen_symbols.add(symbol.lower())
                candidates.append({
                    "id": cg_id or f"dex_{chain.lower()}_{symbol.lower()}",
                    "coingecko_id": cg_id,
                    "symbol": symbol,
                    "name": name,
                    "chain": chain,
                    "contract_address": contract_addr,
                    "current_price": price,
                    "market_cap": mc_usd,
                    "fully_diluted_valuation": fdv_usd or mc_usd,
                    "total_volume": eff_vol,
                    "liquidity_usd": liq_usd,
                    "price_change_1h": chg_1h,
                    "price_change_6h": chg_6h,
                    "price_change_percentage_24h": chg_24h,
                    "price_change_percentage_7d_in_currency": chg_24h,
                    "ath_change_percentage": -15.0,
                    "buys_24h": buys_24h,
                    "sells_24h": sells_24h,
                    "buy_ratio": effective_buy_ratio,
                    "pool_age_hours": pool_age_h,
                    "age_label": _format_age_label(pool_age_h),
                    "position_score": pos_score,
                    "position_tag": pos_tag,
                    "is_meme_candidate": True,
                    "initial_opp_type": "🐶 链上早期Meme/金狗",
                    "track_name": f"{chain} {source_tag}",
                    "dex_url": f"https://dexscreener.com/{chain.lower()}/{contract_addr}" if contract_addr else "",
                })
        except Exception as e:
            print(f"⚠️ GeckoTerminal ({source_tag}) 抓取异常: {e}")

    # 1.2 DexScreener 最新社区助推早期池 (严控市值 <= max_meme_mc_usd 且未暴涨过头)
    try:
        resp = requests.get("https://api.dexscreener.com/token-boosts/top/v1", timeout=12)
        if resp.status_code == 200 and isinstance(resp.json(), list):
            for b in resp.json()[:14]:
                token_addr = b.get("tokenAddress")
                chain_id = (b.get("chainId") or "").upper()
                if not token_addr:
                    continue
                pair_resp = requests.get(
                    f"https://api.dexscreener.com/latest/dex/tokens/{token_addr}",
                    timeout=10,
                )
                if pair_resp.status_code == 200:
                    pairs = pair_resp.json().get("pairs") or []
                    if not pairs:
                        continue
                    best_pair = max(
                        pairs,
                        key=lambda x: float((x.get("liquidity") or {}).get("usd") or 0),
                    )
                    base_tok = best_pair.get("baseToken") or {}
                    sym = (base_tok.get("symbol") or "").strip().upper()
                    nm = base_tok.get("name") or sym
                    if not sym or sym.lower() in seen_symbols:
                        continue

                    liq = float((best_pair.get("liquidity") or {}).get("usd") or 0)
                    fdv = float(best_pair.get("fdv") or 0)
                    mc = float(best_pair.get("marketCap") or fdv or (liq * 5) or 0)
                    vol24 = float((best_pair.get("volume") or {}).get("h24") or 0)
                    chg1h = float((best_pair.get("priceChange") or {}).get("h1") or 0)
                    chg6h = float((best_pair.get("priceChange") or {}).get("h6") or 0)
                    chg24h = float((best_pair.get("priceChange") or {}).get("h24") or 0)
                    pool_age_h = _calc_pool_age_hours(best_pair.get("pairCreatedAt"))

                    tx24 = (best_pair.get("txns") or {}).get("h24") or {}
                    buys = int(tx24.get("buys") or 0)
                    sells = int(tx24.get("sells") or 0)
                    tot_tx = buys + sells
                    b_ratio = round((buys / tot_tx) * 100, 1) if tot_tx > 0 else 50.0

                    if is_excluded_token("", sym, nm, mc, max_mc_usd=max_meme_mc_usd):
                        continue
                    if liq < 30_000 or mc < 150_000 or mc > max_meme_mc_usd or vol24 < 100_000:
                        continue

                    ok_entry, pos_score, pos_tag = assess_entry_position(
                        chg1h, chg6h, chg24h, b_ratio, mc, pool_age_h, guardrails, is_meme=True
                    )
                    if not ok_entry:
                        continue

                    seen_symbols.add(sym.lower())
                    candidates.append({
                        "id": f"dex_{chain_id.lower()}_{sym.lower()}",
                        "coingecko_id": "",
                        "symbol": sym,
                        "name": nm,
                        "chain": chain_id,
                        "contract_address": token_addr,
                        "current_price": float(best_pair.get("priceUsd") or 0),
                        "market_cap": mc,
                        "fully_diluted_valuation": fdv or mc,
                        "total_volume": vol24,
                        "liquidity_usd": liq,
                        "price_change_1h": chg1h,
                        "price_change_6h": chg6h,
                        "price_change_percentage_24h": chg24h,
                        "price_change_percentage_7d_in_currency": chg24h,
                        "ath_change_percentage": -15.0,
                        "buys_24h": buys,
                        "sells_24h": sells,
                        "buy_ratio": b_ratio,
                        "pool_age_hours": pool_age_h,
                        "age_label": _format_age_label(pool_age_h),
                        "position_score": pos_score,
                        "position_tag": pos_tag,
                        "is_meme_candidate": True,
                        "initial_opp_type": "🐶 链上早期Meme/金狗",
                        "track_name": f"{chain_id} 社区早期助推",
                        "dex_url": best_pair.get("url") or f"https://dexscreener.com/{chain_id.lower()}/{token_addr}",
                    })
    except Exception as e:
        print(f"⚠️ DexScreener Boosted 抓取异常: {e}")

    # 按买点位置得分 + 买盘占比排序，优先挑选刚点火且账龄最新的标的
    candidates.sort(key=lambda x: (x.get("position_score", 70), x.get("buy_ratio", 50)), reverse=True)
    print(f"🐶 [引擎1-链上极早期狙击] 严选出 {len(candidates)} 个最佳买点位置的早期链上标的")
    return candidates[:7]


# ==============================================================================
# 引擎 2：全网早期小市值异动黑马引擎 (严控市值 $100万 ~ $4500万 + 严禁高位接盘)
# ==============================================================================
def fetch_narrative_breakout_candidates(guardrails):
    """捕捉全网热搜与小市值异动中处于早期启动窗口 ($1M ~ $45M) 的黑马"""
    candidates = []
    max_mc_usd = float(guardrails.get("max_narrative_mc_wan", 5000.0)) * 10000.0

    try:
        resp = requests.get("https://api.coingecko.com/api/v3/search/trending", headers=cg_headers(), timeout=15)
        if resp.status_code == 200:
            coins = resp.json().get("coins", [])
            trending_ids = [item.get("item", {}).get("id") for item in coins if item.get("item", {}).get("id")]
            if trending_ids:
                m_url = "https://api.coingecko.com/api/v3/coins/markets"
                params = {
                    "vs_currency": "usd",
                    "ids": ",".join(trending_ids[:15]),
                    "order": "volume_desc",
                    "price_change_percentage": "1h,24h,7d",
                }
                m_resp = requests.get(m_url, headers=cg_headers(), params=params, timeout=15)
                if m_resp.status_code == 200:
                    for c in m_resp.json():
                        mc = float(c.get("market_cap") or 0)
                        vol = float(c.get("total_volume") or 0)
                        if is_excluded_token(c.get("id"), c.get("symbol"), c.get("name"), mc, max_mc_usd=max_mc_usd):
                            continue
                        if mc < 800_000 or vol < 800_000:
                            continue

                        chg1h = float(c.get("price_change_percentage_1h_in_currency") or 0)
                        chg24h = float(c.get("price_change_percentage_24h") or 0)
                        ok_entry, pos_score, pos_tag = assess_entry_position(
                            chg1h, chg24h * 0.5, chg24h, 54.5, mc, 120.0, guardrails, is_meme=False
                        )
                        if not ok_entry:
                            continue

                        c["coingecko_id"] = c.get("id")
                        c["chain"] = "MULTI"
                        c["contract_address"] = ""
                        c["liquidity_usd"] = 0
                        c["price_change_1h"] = chg1h
                        c["price_change_6h"] = chg24h * 0.5
                        c["buys_24h"] = 0
                        c["sells_24h"] = 0
                        c["buy_ratio"] = 54.5
                        c["pool_age_hours"] = 120.0
                        c["age_label"] = "⚡ 早期热搜异动"
                        c["position_score"] = pos_score
                        c["position_tag"] = pos_tag
                        c["is_meme_candidate"] = False
                        c["initial_opp_type"] = "🚀 叙事异动黑马"
                        c["track_name"] = "待深度背调验真"
                        c["dex_url"] = ""
                        candidates.append(c)
    except Exception as e:
        print(f"⚠️ [引擎2-叙事异动黑马] 扫描异常: {e}")

    print(f"🚀 [引擎2-早期叙事黑马] 剔除高位币与大市值白马后，捕获 {len(candidates)} 个早期启动标的")
    return candidates[:5]


# ==============================================================================
# 引擎 3：细分赛道早期小市值黑马 & 黄金坑右侧拐点潜伏引擎
# ==============================================================================
def fetch_sector_alpha_candidates(track_id, track_name, guardrails):
    """
    在重点赛道内寻找市值 $80万 ~ $4500万 的早期标的：
    1. 【📈 强势赛道龙头(早期启动)】：24h 温和放量上涨 (+2% ~ +35%) 且 1h 为正，绝不追高已暴涨 80%+ 的老龙头
    2. 【💎 机构潜伏/底部价值(黄金坑拐点)】：距 ATH 跌幅 >= 50%，流通率 >= 40%，且今日 1h/24h 刚出现放量止跌转阳信号
    """
    candidates = []
    max_mc_usd = float(guardrails.get("max_narrative_mc_wan", 5000.0)) * 10000.0
    sweet_max = float(guardrails.get("sweet_spot_24h_max", 38.0))

    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "category": track_id,
        "order": "volume_desc",
        "per_page": 80,
        "page": 1,
        "price_change_percentage": "1h,24h,7d",
    }
    try:
        resp = requests.get(url, headers=cg_headers(), params=params, timeout=15)
        if resp.status_code != 200:
            return []
        coins = resp.json()
        ignition_list = []
        reversal_list = []

        for c in coins:
            mc = float(c.get("market_cap") or 0)
            if is_excluded_token(c.get("id"), c.get("symbol"), c.get("name"), mc, max_mc_usd=max_mc_usd):
                continue
            if mc < 800_000:
                continue

            fdv = float(c.get("fully_diluted_valuation") or mc)
            vol = float(c.get("total_volume") or 0)
            ath_drop = float(c.get("ath_change_percentage") or 0)
            chg_1h = float(c.get("price_change_percentage_1h_in_currency") or 0)
            chg_24h = float(c.get("price_change_percentage_24h") or 0)
            mc_fdv = mc / fdv if fdv > 0 else 1.0
            turnover = vol / mc if mc > 0 else 0

            ok_entry, pos_score, pos_tag = assess_entry_position(
                chg_1h, chg_24h * 0.5, chg_24h, 54.0, mc, 240.0, guardrails, is_meme=("meme" in track_id.lower())
            )
            if not ok_entry:
                continue

            c["coingecko_id"] = c.get("id")
            c["chain"] = "MULTI"
            c["contract_address"] = ""
            c["liquidity_usd"] = 0
            c["price_change_1h"] = chg_1h
            c["price_change_6h"] = chg_24h * 0.5
            c["buys_24h"] = 0
            c["sells_24h"] = 0
            c["buy_ratio"] = 54.0
            c["pool_age_hours"] = 240.0
            c["age_label"] = "🎯 赛道小盘精选"
            c["position_score"] = pos_score
            c["position_tag"] = pos_tag
            c["is_meme_candidate"] = "meme" in track_id.lower()
            c["track_name"] = track_name
            c["dex_url"] = ""

            # 1. 早期启动龙头：市值小、24h涨幅处于温和启动甜蜜区(2.5% ~ sweet_max)、1h 正动量、换手活跃
            if 2.5 <= chg_24h <= sweet_max and chg_1h >= 0.0 and turnover >= 0.12 and vol >= 600_000:
                c_copy = dict(c)
                c_copy["initial_opp_type"] = "📈 强势赛道龙头"
                ignition_list.append(c_copy)

            # 2. 黄金坑右侧拐点：超跌 >= 50%、高流通率 >= 40%、今日止跌转阳(-2% ~ +18%)且 1h 向上
            elif ath_drop <= -50.0 and mc_fdv >= 0.40 and -2.0 <= chg_24h <= 18.0 and chg_1h >= 0.2 and vol >= 500_000:
                c_copy = dict(c)
                c_copy["initial_opp_type"] = "💎 机构潜伏/底部价值"
                c_copy["position_tag"] = "💎 黄金坑右侧拐点"
                reversal_list.append(c_copy)

        # 优先选择市值更小（赔率更高）且买点得分更高的标的
        ignition_list.sort(key=lambda x: (x.get("position_score", 80), -float(x.get("market_cap") or 0)), reverse=True)
        reversal_list.sort(key=lambda x: (float(x.get("price_change_1h") or 0), -float(x.get("market_cap") or 0)), reverse=True)
        candidates.extend(ignition_list[:2])
        candidates.extend(reversal_list[:2])
    except Exception as e:
        print(f"⚠️ 扫描赛道 {track_name} 异常: {e}")

    return candidates


# ==============================================================================
# 强制深度背调管道 (Deep Research + 链上真实买盘与池子账龄二次验真)
# ==============================================================================
def conduct_deep_research(coin):
    cg_id = coin.get("coingecko_id") or ""
    symbol = (coin.get("symbol") or "").upper()
    name = coin.get("name") or symbol

    real_categories = []
    description_en = ""
    commits_4w = 0
    chain = coin.get("chain") or "MULTI"
    contract_addr = coin.get("contract_address") or ""

    if cg_id and not str(cg_id).startswith("dex_"):
        try:
            url = f"https://api.coingecko.com/api/v3/coins/{cg_id}?localization=false&tickers=false&market_data=false&community_data=true&developer_data=true"
            resp = requests.get(url, headers=cg_headers(), timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                real_categories = [cat for cat in (data.get("categories") or []) if cat]
                raw_desc = (data.get("description") or {}).get("en") or ""
                clean_desc = re.sub(r"<[^>]+>", "", raw_desc).strip()
                description_en = clean_desc[:350]

                dev = data.get("developer_data") or {}
                commits_4w = int(dev.get("commit_count_4_weeks") or 0)

                platforms = data.get("platforms") or {}
                for plat_name, addr in platforms.items():
                    if plat_name and addr:
                        chain = plat_name.upper()[:10]
                        contract_addr = addr
                        break
        except Exception as e:
            print(f"   ⚠️ CG 深度背调 {symbol} 异常: {e}")

    if real_categories:
        cat_joined = " | ".join(real_categories).lower()
        is_really_meme = any(k in cat_joined for k in ["meme", "dog", "cat", "pump.fun", "frog", "elon"])
        is_utility_project = any(
            k in cat_joined
            for k in [
                "layer 1", "layer 2", "defi", "decentralized finance", "oracle",
                "artificial intelligence", "depin", "real world assets", "rwa",
                "infrastructure", "smart contract", "gaming", "gamefi", "storage",
                "privacy", "zero knowledge", "zk", "dex", "lending", "derivatives",
            ]
        )
        if is_utility_project and not is_really_meme:
            coin["is_meme_candidate"] = False
            if coin.get("initial_opp_type") == "🐶 链上早期Meme/金狗":
                coin["initial_opp_type"] = "🚀 叙事异动黑马"
        elif is_really_meme and not is_utility_project:
            coin["is_meme_candidate"] = True
            coin["initial_opp_type"] = "🐶 链上早期Meme/金狗"

        ignored_generic = {
            "alleged sec securities", "ftx holdings",
            "alameda research portfolio", "made in usa",
        }
        meaningful_cats = [
            c for c in real_categories
            if c.lower() not in ignored_generic
            and "ecosystem" not in c.lower()
            and "portfolio" not in c.lower()
        ]
        if meaningful_cats and coin.get("track_name") in ["待深度背调验真", "全网热搜异动榜", ""]:
            coin["track_name"] = meaningful_cats[0][:22]

    # DexScreener 链上深度核验（补全真实流动性、买卖单比例、池子创建账龄）
    if float(coin.get("liquidity_usd") or 0) == 0 or not coin.get("dex_url"):
        try:
            q = contract_addr if contract_addr else symbol
            d_resp = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={q}", timeout=10)
            if d_resp.status_code == 200:
                pairs = d_resp.json().get("pairs") or []
                matching_pairs = [
                    p for p in pairs
                    if ((p.get("baseToken") or {}).get("symbol") or "").upper() == symbol
                ]
                if matching_pairs:
                    best_p = max(
                        matching_pairs,
                        key=lambda x: float((x.get("liquidity") or {}).get("usd") or 0),
                    )
                    liq = float((best_p.get("liquidity") or {}).get("usd") or 0)
                    if liq > 0:
                        coin["liquidity_usd"] = liq
                    if not coin.get("dex_url") and best_p.get("url"):
                        coin["dex_url"] = best_p.get("url")
                    if chain in ["MULTI", "MEME", ""] and best_p.get("chainId"):
                        chain = best_p.get("chainId").upper()
                    if best_p.get("pairCreatedAt") and coin.get("pool_age_hours", 999) >= 120:
                        age_h = _calc_pool_age_hours(best_p.get("pairCreatedAt"))
                        coin["pool_age_hours"] = age_h
                        coin["age_label"] = _format_age_label(age_h)
                    tx24 = (best_p.get("txns") or {}).get("h24") or {}
                    b24 = int(tx24.get("buys") or 0)
                    s24 = int(tx24.get("sells") or 0)
                    if b24 + s24 > 0 and coin.get("buys_24h", 0) == 0:
                        coin["buys_24h"] = b24
                        coin["sells_24h"] = s24
                        coin["buy_ratio"] = round((b24 / (b24 + s24)) * 100, 1)
        except Exception:
            pass

    vc_hits = []
    news_snippets = []
    if TAVILY_API_KEY:
        try:
            if coin.get("is_meme_candidate"):
                query = f'"{symbol}" "{name}" meme coin crypto community catalyst why pumping'
            else:
                query = f'"{name}" ({symbol}) crypto project funding investors catalyst news'
            t_resp = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": TAVILY_API_KEY,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": 3,
                },
                timeout=12,
            )
            if t_resp.status_code == 200:
                results = t_resp.json().get("results", [])
                combined_text = " ".join([r.get("content", "") for r in results]).lower()
                news_snippets = [r.get("content", "")[:140] for r in results[:2]]
                top_vcs = [
                    "binance", "a16z", "paradigm", "polychain", "coinbase",
                    "pantera", "multicoin", "animoca", "sequoia", "dragonfly",
                    "okx", "solana ventures",
                ]
                vc_hits = [vc.upper() for vc in top_vcs if vc in combined_text]
        except Exception:
            pass

    coin["chain"] = chain
    coin["contract_address"] = contract_addr
    coin["real_categories"] = real_categories[:5]
    coin["description_en"] = description_en
    coin["commits_4w"] = commits_4w
    coin["vc_hits"] = vc_hits
    coin["news_snippets"] = news_snippets
    return coin


# ==============================================================================
# V6.0 五维进化量化评分系统（将【早期时机与买点位置】设为最高权重）
# ==============================================================================
def calculate_quant_score(coin, track_heat_score, weights):
    mc = float(coin.get("market_cap") or 1)
    fdv = float(coin.get("fully_diluted_valuation") or mc)
    vol = float(coin.get("total_volume") or 0)
    chg_1h = float(coin.get("price_change_1h") or 0)
    liq = float(coin.get("liquidity_usd") or 0)
    buy_ratio = float(coin.get("buy_ratio") or 52.0)
    pos_score = float(coin.get("position_score") or 80.0)
    commits = int(coin.get("commits_4w") or 0)
    vc_hits = coin.get("vc_hits") or []

    turnover = vol / mc if mc > 0 else 0
    mc_fdv_ratio = mc / fdv if fdv > 0 else 1.0

    # 1. 买点位置与早期时机分 (early_timing)
    timing_score = pos_score

    # 2. 链上买盘压制与换手爆发分 (buy_pressure)
    buy_bonus = min(max((buy_ratio - 48.0) * 3.2, 0), 28)
    turn_bonus = 18 if 0.18 <= turnover <= 2.5 else (10 if turnover > 2.5 else 5)
    mom_bonus = 8 if 0.5 <= chg_1h <= 20.0 else 0
    buy_pressure_score = min(50 + buy_bonus + turn_bonus + mom_bonus, 98)

    # 3. 小市值高赔率空间分 (mc_odds) —— 市值越小且池子健康，十倍赔率越高！
    if coin.get("is_meme_candidate"):
        if 200_000 <= mc <= 5_000_000:
            mc_odds_score = 96
        elif 5_000_000 < mc <= 12_000_000:
            mc_odds_score = 86
        else:
            mc_odds_score = 72
    else:
        if 1_000_000 <= mc <= 18_000_000:
            mc_odds_score = 96
        elif 18_000_000 < mc <= 38_000_000:
            mc_odds_score = 86
        else:
            mc_odds_score = 74

    # 4. 基本面/流动性/筹码结构分 (fundamentals)
    if coin.get("is_meme_candidate"):
        fundamentals_score = 94 if liq >= 120_000 else (84 if liq >= 50_000 else 72)
    else:
        vc_part = min(len(vc_hits) * 15, 30)
        dev_part = min(commits * 2, 20)
        unlock_part = min(mc_fdv_ratio * 45, 45)
        fundamentals_score = min(45 + vc_part + dev_part + unlock_part, 96)

    quant_total = (
        timing_score * weights.get("early_timing", 0.30)
        + buy_pressure_score * weights.get("buy_pressure", 0.25)
        + mc_odds_score * weights.get("mc_odds", 0.20)
        + track_heat_score * weights.get("track_heat", 0.15)
        + fundamentals_score * weights.get("fundamentals", 0.10)
    )

    return round(quant_total, 1), round(mc_fdv_ratio * 100, 1), round(turnover * 100, 1)


def run_job2():
    print("🚀 [Job 2 V6.0] 启动极早期点火狙击引擎 + 动态进化风控闸门...")
    local_data = notifier.load_local_db()
    evo_state = local_data.get("evolution_state") or copy.deepcopy(DEFAULT_EVOLUTION_STATE)
    guardrails = evo_state.get("guardrails") or DEFAULT_EVOLUTION_STATE["guardrails"]

    db = FeishuDB()
    weights = db.get_strategy_weights(evo_state)
    min_score_threshold = float(guardrails.get("min_score_threshold", 68.0))

    print(
        f"🧬 当前适用第 Gen #{evo_state.get('generation', 1)} 代进化闸门: "
        f"Meme市值上限=${guardrails.get('max_meme_mc_wan')}万 | "
        f"叙事币市值上限=${guardrails.get('max_narrative_mc_wan')}万 | "
        f"24h防追高红线=+{guardrails.get('max_24h_pump_limit')}% | "
        f"最低买盘比={guardrails.get('min_buy_ratio_pct')}%"
    )

    approved_tracks = db.get_approved_tracks()
    if not approved_tracks:
        approved_tracks = local_data.get("tracks", [])

    candidate_pool = []
    seen_keys = set()

    # 1. 启动【引擎 1：链上极早期新池与点火金狗狙击】
    for m_coin in fetch_onchain_meme_candidates(guardrails):
        key = (m_coin.get("symbol") or "").lower()
        if key and key not in seen_keys:
            seen_keys.add(key)
            m_coin["track_heat"] = 92
            candidate_pool.append(m_coin)

    # 2. 启动【引擎 2：全网小市值早期叙事异动黑马】
    for n_coin in fetch_narrative_breakout_candidates(guardrails):
        key = (n_coin.get("symbol") or "").lower()
        if key and key not in seen_keys:
            seen_keys.add(key)
            n_coin["track_heat"] = 88
            candidate_pool.append(n_coin)

    # 3. 启动【引擎 3：重点赛道小盘早期龙头与黄金坑右侧拐点】
    for track in approved_tracks[:4]:
        t_id = track.get("id") or track.get("赛道ID") or ""
        t_name = track.get("name") or track.get("赛道名称") or t_id
        if not t_id or t_id == "trending-meme":
            continue
        t_change = float(track.get("change_24h") or track.get("24h涨幅(%)") or 0)
        t_heat = min(max(74 + t_change * 2.0, 68), 96)

        print(f"🔎 正在深挖赛道早期标的: {t_name} ({t_id})...")
        t_coins = fetch_sector_alpha_candidates(t_id, t_name, guardrails)
        for c in t_coins:
            key = (c.get("symbol") or "").lower()
            if key and key not in seen_keys:
                seen_keys.add(key)
                c["track_heat"] = t_heat
                candidate_pool.append(c)
        time.sleep(1.0)

    print(f"📊 三大早期引擎共捕获 {len(candidate_pool)} 个处于黄金建仓窗口的候选标的，开始执行【强制深度背调】...")

    selected_projects = []
    tz_bj = timezone(timedelta(hours=8))
    now_str = datetime.now(tz_bj).strftime("%Y-%m-%d %H:%M")

    max_meme_usd = float(guardrails.get("max_meme_mc_wan", 1500.0)) * 10000.0
    max_narr_usd = float(guardrails.get("max_narrative_mc_wan", 5000.0)) * 10000.0

    for coin in candidate_pool[:12]:
        sym = (coin.get("symbol") or "").upper()
        print(f"🕵️‍♂️ 正在深度背调: ${sym} ({coin.get('name')}) | 初筛位置: {coin.get('position_tag')}...")
        coin = conduct_deep_research(coin)

        # 背调后二次校验市值上限与真实链上买盘比（防止假拉盘）
        cap_limit = max_meme_usd if coin.get("is_meme_candidate") else max_narr_usd
        if is_excluded_token(coin.get("coingecko_id"), sym, coin.get("name"), coin.get("market_cap"), max_mc_usd=cap_limit):
            print(f"   ⏭️ ${sym} 经背调市值超标或属于老白马，已剔除")
            continue

        if float(coin.get("buy_ratio") or 50.0) < 48.5:
            print(f"   ⏭️ ${sym} 链上真实卖盘大于买盘 (买盘仅 {coin.get('buy_ratio')}%)，存在派发风险，已剔除")
            continue

        quant_score, mc_fdv_pct, turnover_pct = calculate_quant_score(
            coin, coin.get("track_heat", 82), weights
        )
        if quant_score < (min_score_threshold - 4):
            continue

        dossier = {
            "symbol": sym,
            "name": coin.get("name"),
            "chain": coin.get("chain", "MULTI"),
            "age_label": coin.get("age_label", "早期标的"),
            "pool_age_hours": coin.get("pool_age_hours", 120),
            "position_tag": coin.get("position_tag", "🟢 早期启动窗口"),
            "is_meme_candidate": coin.get("is_meme_candidate", False),
            "initial_opp_type": coin.get("initial_opp_type"),
            "coingecko_categories": coin.get("real_categories", []),
            "description": coin.get("description_en", "暂无简介"),
            "price_usd": coin.get("current_price"),
            "change_1h_pct": round(float(coin.get("price_change_1h") or 0), 2),
            "change_6h_pct": round(float(coin.get("price_change_6h") or 0), 2),
            "change_24h_pct": round(float(coin.get("price_change_percentage_24h") or 0), 2),
            "market_cap_wan_usd": round(float(coin.get("market_cap") or 0) / 10000, 1),
            "liquidity_wan_usd": round(float(coin.get("liquidity_usd") or 0) / 10000, 1),
            "turnover_24h_pct": turnover_pct,
            "mc_fdv_ratio_pct": mc_fdv_pct,
            "onchain_buys_24h": coin.get("buys_24h", 0),
            "onchain_sells_24h": coin.get("sells_24h", 0),
            "onchain_buy_ratio_pct": coin.get("buy_ratio", 52.0),
            "github_commits_4w": coin.get("commits_4w", 0),
            "vc_endorsements": coin.get("vc_hits", []),
            "latest_news_catalysts": coin.get("news_snippets", []),
            "quant_score": quant_score,
        }

        ai_score, debate_report, verified_type, verified_track, catalyst, entry_timing = multi_agent_evaluate(
            dossier, evo_state
        )
        # 若 CIO 判定位置过高/接盘风险(ai_score < 62)，直接一票否决！
        if ai_score < 62:
            print(f"   🛑 ${sym} 被 CIO 一票否决 (AI打分 {ai_score}: 买点位置偏高或赔率不足)")
            continue

        final_score = round(quant_score * 0.50 + ai_score * 0.50, 1)

        if final_score >= min_score_threshold:
            final_track = verified_track or coin.get("track_name") or "早期叙事Alpha"
            cur_price = float(coin.get("current_price") or 0)
            p_data = {
                "id": coin.get("id"),
                "coingecko_id": coin.get("coingecko_id") or "",
                "symbol": sym,
                "name": coin.get("name"),
                "chain": coin.get("chain", "MULTI"),
                "contract_address": coin.get("contract_address", ""),
                "opp_type": verified_type,
                "entry_timing": entry_timing,
                "age_label": coin.get("age_label", "早期标的"),
                "pool_age_hours": coin.get("pool_age_hours", 120),
                "track": final_track,
                "catalyst": catalyst,
                "price": cur_price,
                "live_price": cur_price,
                "live_roi_pct": 0.0,
                "change_1h": round(float(coin.get("price_change_1h") or 0), 2),
                "change_24h": round(float(coin.get("price_change_percentage_24h") or 0), 2),
                "change_7d": round(float(coin.get("price_change_percentage_7d_in_currency") or 0), 2),
                "turnover_24h": turnover_pct,
                "market_cap": round(float(coin.get("market_cap") or 0) / 10000, 2),
                "liquidity_wan": round(float(coin.get("liquidity_usd") or 0) / 10000, 2),
                "buys_24h": coin.get("buys_24h", 0),
                "sells_24h": coin.get("sells_24h", 0),
                "buy_ratio": coin.get("buy_ratio", 52.0),
                "mc_fdv_ratio": mc_fdv_pct,
                "ath_drop": round(float(coin.get("ath_change_percentage") or 0), 2),
                "commits_4w": coin.get("commits_4w", 0),
                "vc_hits": coin.get("vc_hits", []),
                "final_score": final_score,
                "ai_report": debate_report,
                "dex_url": coin.get("dex_url") or f"https://dexscreener.com/search?q={sym}",
                "discovered_at": now_str,
            }
            db.save_alpha_project(p_data)
            selected_projects.append(p_data)
            print(
                f"   ✅ 早期狙击入选! ${sym} | 窗口: {entry_timing} | 市值: ${p_data['market_cap']}万 | 综合得分: {final_score}"
            )
        time.sleep(1.0)

    latest_local = notifier.load_local_db()
    selected_projects.sort(key=lambda x: x["final_score"], reverse=True)
    if selected_projects:
        merged = list(selected_projects)
        existing_syms = {p["symbol"].upper() for p in merged}
        for old_p in latest_local.get("projects", []):
            old_sym = str(old_p.get("symbol", "")).upper()
            old_mc_usd = float(old_p.get("market_cap") or 0) * 10000
            # 自动清理历史遗留的高市值老项目或严重亏损破位项目
            old_roi = float(old_p.get("live_roi_pct") or 0)
            if (
                old_sym
                and old_sym not in existing_syms
                and old_roi > -18.0
                and not is_excluded_token(old_p.get("id", ""), old_sym, old_p.get("name", ""), old_mc_usd, max_mc_usd=max_narr_usd)
            ):
                existing_syms.add(old_sym)
                merged.append(old_p)
        latest_local["projects"] = merged[:18]
        notifier.save_local_db(latest_local)

    notifier.send_wechat(
        "🎯 [V6.0 早期点火狙击战报] 深度背调完成",
        f"本轮共捕获 {len(selected_projects)} 个处于早期最佳建仓窗口的高赔率标的",
    )


if __name__ == "__main__":
    run_job2()
