# job2_project_hunter.py - V5.0 三大早期捕获引擎 + 强制深度背调系统
import re
import time
import requests
from datetime import datetime, timezone, timedelta
from config import COINGECKO_API_KEY, TAVILY_API_KEY
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

# 2. 铁律排除：大市值老牌白马与主流公链（只抓早期、高赔率、高爆发潜力项目）
MEGA_CAP_BLACKLIST = {
    "bitcoin", "ethereum", "tether", "binancecoin", "solana", "ripple", "usd-coin",
    "cardano", "dogecoin", "tron", "chainlink", "avalanche-2", "toncoin", "shiba-inu",
    "stellar", "polkadot", "sui", "bitcoin-cash", "hedera-hashgraph", "litecoin",
    "near", "uniswap", "pepe", "aptos", "internet-computer", "monero", "pol-ex-matic",
    "ethereum-classic", "dai", "okb", "cronos", "aave", "mantle", "vechain", "render-token",
    "bittensor", "filecoin", "arbitrum", "optimism", "cosmos", "injective-protocol",
    "immutable-x", "fantom", "the-graph", "theta-token", "algorand", "maker", "sei-network",
    "bonk", "floki", "worldcoin-wld", "celestia", "lido-dao", "gala", "flow", "eos",
}

MEGA_CAP_SYMBOLS = {
    "btc", "eth", "sol", "bnb", "xrp", "ada", "doge", "trx", "link", "avax",
    "ton", "shib", "dot", "near", "uni", "ltc", "bch", "icp", "etc", "apt",
    "sui", "arb", "op", "atom", "fil", "xlm", "hbar", "vet", "aave", "mkr",
}


def cg_headers():
    headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    if COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = COINGECKO_API_KEY
    return headers


def is_excluded_token(coin_id="", symbol="", name="", market_cap=0, max_mc_usd=350_000_000):
    """排除稳定币、包装币以及高市值老牌白马（默认市值上限 3.5 亿美元）"""
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


# ==============================================================================
# 引擎 1：链上早期 Meme / 金狗专属狙击引擎 (GeckoTerminal + DexScreener + CG 小市值 Meme)
# ==============================================================================
def fetch_onchain_meme_candidates():
    """从链上实时交易池和助推榜捕捉高换手、买盘强劲的早期 Meme 与金狗"""
    candidates = []
    seen_symbols = set()

    # 1.1 GeckoTerminal 实时链上热门交易池 (Solana / Base / ETH / BSC 等)
    try:
        url = "https://api.geckoterminal.com/api/v2/networks/trending_pools?include=base_token&page=1"
        resp = requests.get(
            url,
            headers={"Accept": "application/json;version=20230302", "User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        if resp.status_code == 200:
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
                mc_usd = float(attrs.get("market_cap_usd") or fdv_usd or (liq_usd * 6) or 0)

                if is_excluded_token(cg_id, symbol, name, mc_usd, max_mc_usd=150_000_000):
                    continue

                # Meme 铁律筛选：池子流动性 >= $35,000（防貔貅/防归零池），市值在 $20万 ~ $1.5亿 之间
                if liq_usd < 35_000 or mc_usd < 200_000 or mc_usd > 150_000_000:
                    continue

                vol_24h = float((attrs.get("volume_usd") or {}).get("h24") or 0)
                chg_1h = float((attrs.get("price_change_percentage") or {}).get("h1") or 0)
                chg_6h = float((attrs.get("price_change_percentage") or {}).get("h6") or 0)
                chg_24h = float((attrs.get("price_change_percentage") or {}).get("h24") or 0)

                txns_24h = (attrs.get("transactions") or {}).get("h24") or {}
                buys_24h = int(txns_24h.get("buys") or 0)
                sells_24h = int(txns_24h.get("sells") or 0)
                total_txns = buys_24h + sells_24h
                buy_ratio = round((buys_24h / total_txns) * 100, 1) if total_txns > 0 else 50.0

                # 必须有真实资金推动：24h成交额 >= $120,000 且 (24h或6h为正涨幅) 且 交易笔数活跃
                if vol_24h < 120_000 or (chg_24h < 5 and chg_6h < 5) or total_txns < 150:
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
                    "total_volume": vol_24h,
                    "liquidity_usd": liq_usd,
                    "price_change_1h": chg_1h,
                    "price_change_6h": chg_6h,
                    "price_change_percentage_24h": chg_24h,
                    "price_change_percentage_7d_in_currency": chg_24h,
                    "ath_change_percentage": -20.0,
                    "buys_24h": buys_24h,
                    "sells_24h": sells_24h,
                    "buy_ratio": buy_ratio,
                    "is_meme_candidate": True,
                    "initial_opp_type": "🐶 链上早期Meme/金狗",
                    "track_name": f"{chain} 链上热池金狗",
                    "dex_url": f"https://dexscreener.com/{chain.lower()}/{contract_addr}" if contract_addr else "",
                })
    except Exception as e:
        print(f"⚠️ GeckoTerminal 链上热门池抓取异常: {e}")

    # 1.2 DexScreener Top Boosted 社区助推金狗捕捉
    try:
        resp = requests.get("https://api.dexscreener.com/token-boosts/top/v1", timeout=12)
        if resp.status_code == 200:
            boosts = resp.json()
            if isinstance(boosts, list):
                for b in boosts[:12]:
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
                        tx24 = (best_pair.get("txns") or {}).get("h24") or {}
                        buys = int(tx24.get("buys") or 0)
                        sells = int(tx24.get("sells") or 0)
                        tot_tx = buys + sells
                        b_ratio = round((buys / tot_tx) * 100, 1) if tot_tx > 0 else 50.0

                        if is_excluded_token("", sym, nm, mc, max_mc_usd=120_000_000):
                            continue
                        if liq < 40_000 or mc < 250_000 or vol24 < 150_000 or (chg24h < 5 and chg6h < 5):
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
                            "ath_change_percentage": -20.0,
                            "buys_24h": buys,
                            "sells_24h": sells,
                            "buy_ratio": b_ratio,
                            "is_meme_candidate": True,
                            "initial_opp_type": "🐶 链上早期Meme/金狗",
                            "track_name": f"{chain_id} 社区助推金狗",
                            "dex_url": best_pair.get("url") or f"https://dexscreener.com/{chain_id.lower()}/{token_addr}",
                        })
    except Exception as e:
        print(f"⚠️ DexScreener Boosted 抓取异常: {e}")

    # 1.3 CoinGecko 小市值高换手 Meme 专项扫描 ($1M ~ $80M 市值，排除大市值老 Meme)
    try:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {
            "vs_currency": "usd",
            "category": "meme-token",
            "order": "volume_desc",
            "per_page": 50,
            "page": 1,
            "price_change_percentage": "1h,24h,7d",
        }
        resp = requests.get(url, headers=cg_headers(), params=params, timeout=15)
        if resp.status_code == 200:
            for c in resp.json():
                sym = (c.get("symbol") or "").upper()
                if not sym or sym.lower() in seen_symbols:
                    continue
                mc = float(c.get("market_cap") or 0)
                vol = float(c.get("total_volume") or 0)
                chg24 = float(c.get("price_change_percentage_24h") or 0)
                if 1_000_000 <= mc <= 80_000_000 and chg24 >= 8.0 and (vol / mc) >= 0.25:
                    if is_excluded_token(c.get("id"), sym, c.get("name"), mc, max_mc_usd=80_000_000):
                        continue
                    seen_symbols.add(sym.lower())
                    c["coingecko_id"] = c.get("id")
                    c["chain"] = "MEME"
                    c["contract_address"] = ""
                    c["liquidity_usd"] = vol * 0.15
                    c["price_change_1h"] = float(c.get("price_change_percentage_1h_in_currency") or 0)
                    c["price_change_6h"] = chg24 * 0.5
                    c["buys_24h"] = 0
                    c["sells_24h"] = 0
                    c["buy_ratio"] = 55.0
                    c["is_meme_candidate"] = True
                    c["initial_opp_type"] = "🐶 链上早期Meme/金狗"
                    c["track_name"] = "高换手早期Meme"
                    c["dex_url"] = ""
                    candidates.append(c)
    except Exception as e:
        print(f"⚠️ CoinGecko 小市值 Meme 扫描异常: {e}")

    print(f"🐶 [引擎1-链上Meme狙击] 共捕获 {len(candidates)} 个早期高动量 Meme 候选")
    return candidates[:8]


# ==============================================================================
# 引擎 2：全网叙事异动黑马引擎 (严控市值上限 < $3亿，彻底杜绝 NEAR/LINK 等老白马混入)
# ==============================================================================
def fetch_narrative_breakout_candidates(max_mc_usd=300_000_000):
    """捕捉全网热搜与异动榜中市值在 $100万 ~ $3亿 之间的中小市值黑马"""
    candidates = []
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
                        if mc < 1_000_000 or vol < 1_500_000:
                            continue
                        c["coingecko_id"] = c.get("id")
                        c["chain"] = "MULTI"
                        c["contract_address"] = ""
                        c["liquidity_usd"] = 0
                        c["price_change_1h"] = float(c.get("price_change_percentage_1h_in_currency") or 0)
                        c["price_change_6h"] = 0
                        c["buys_24h"] = 0
                        c["sells_24h"] = 0
                        c["buy_ratio"] = 50.0
                        c["is_meme_candidate"] = False
                        c["initial_opp_type"] = "🚀 叙事异动黑马"
                        c["track_name"] = "待深度背调验真"
                        c["dex_url"] = ""
                        candidates.append(c)
    except Exception as e:
        print(f"⚠️ [引擎2-叙事异动黑马] 扫描异常: {e}")

    print(f"🚀 [引擎2-叙事异动黑马] 已过滤大市值白马，捕获 {len(candidates)} 个中小市值异动标的")
    return candidates[:6]


# ==============================================================================
# 引擎 3：强势赛道龙头 & 机构潜伏价值引擎
# ==============================================================================
def fetch_sector_alpha_candidates(track_id, track_name, min_mc_usd=1_500_000, max_mc_usd=300_000_000):
    """在重点赛道内寻找【📈 强势赛道龙头】与【💎 机构潜伏/底部价值】"""
    candidates = []
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "category": track_id,
        "order": "volume_desc",
        "per_page": 45,
        "page": 1,
        "price_change_percentage": "1h,24h,7d",
    }
    try:
        resp = requests.get(url, headers=cg_headers(), params=params, timeout=15)
        if resp.status_code != 200:
            return []
        coins = resp.json()
        rebound_list = []
        value_list = []

        for c in coins:
            mc = float(c.get("market_cap") or 0)
            if is_excluded_token(c.get("id"), c.get("symbol"), c.get("name"), mc, max_mc_usd=max_mc_usd):
                continue
            if mc < min_mc_usd:
                continue

            fdv = float(c.get("fully_diluted_valuation") or mc)
            vol = float(c.get("total_volume") or 0)
            ath_drop = float(c.get("ath_change_percentage") or 0)
            chg_24h = float(c.get("price_change_percentage_24h") or 0)
            mc_fdv = mc / fdv if fdv > 0 else 1.0
            turnover = vol / mc if mc > 0 else 0

            c["coingecko_id"] = c.get("id")
            c["chain"] = "MULTI"
            c["contract_address"] = ""
            c["liquidity_usd"] = 0
            c["price_change_1h"] = float(c.get("price_change_percentage_1h_in_currency") or 0)
            c["price_change_6h"] = 0
            c["buys_24h"] = 0
            c["sells_24h"] = 0
            c["buy_ratio"] = 50.0
            c["is_meme_candidate"] = "meme" in track_id.lower()
            c["track_name"] = track_name
            c["dex_url"] = ""

            # 1. 强势赛道龙头：24h涨幅 >= 4%，换手率 >= 10%
            if chg_24h >= 4.0 and turnover >= 0.10 and vol >= 1_500_000:
                c_copy = dict(c)
                c_copy["initial_opp_type"] = "📈 强势赛道龙头"
                rebound_list.append(c_copy)

            # 2. 机构潜伏/底部价值：距高点跌幅 <= -45%，流通率 >= 35%，成交额 >= 80万
            elif ath_drop <= -45.0 and mc_fdv >= 0.35 and vol >= 800_000 and chg_24h > -8.0:
                c_copy = dict(c)
                c_copy["initial_opp_type"] = "💎 机构潜伏/底部价值"
                value_list.append(c_copy)

        rebound_list.sort(key=lambda x: float(x.get("price_change_percentage_24h") or 0), reverse=True)
        value_list.sort(key=lambda x: float(x.get("total_volume") or 0), reverse=True)
        candidates.extend(rebound_list[:2])
        candidates.extend(value_list[:2])
    except Exception as e:
        print(f"⚠️ 扫描赛道 {track_name} 异常: {e}")

    return candidates


# ==============================================================================
# 核心升级：入选候选项目【强制深度背调管道】 (Deep Research Pipeline)
# ==============================================================================
def conduct_deep_research(coin):
    """
    对初筛确认的候选项目进行全方位深度背调：
    1. 反查 CoinGecko 底层真实分类标签 (Categories)、项目英文简介、公链合约地址、GitHub 提交数
    2. 反查 DexScreener 链上真实流动性、买卖单笔数比、精确 K 线链接
    3. 调用 Tavily 搜索引擎查询项目最新利好催化剂、融资背景与社区热度
    4. 根据真实标签修正是否为 Meme 或价值叙事项目
    """
    cg_id = coin.get("coingecko_id") or ""
    symbol = (coin.get("symbol") or "").upper()
    name = coin.get("name") or symbol

    real_categories = []
    description_en = ""
    commits_4w = 0
    chain = coin.get("chain") or "MULTI"
    contract_addr = coin.get("contract_address") or ""

    # Step 1: CoinGecko 深度元数据背调
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

    # Step 2: 根据真实分类标签，严格纠正 Meme 与非 Meme 归属
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
            "alleged sec securities",
            "ftx holdings",
            "alameda research portfolio",
            "made in usa",
        }
        meaningful_cats = [
            c
            for c in real_categories
            if c.lower() not in ignored_generic
            and "ecosystem" not in c.lower()
            and "portfolio" not in c.lower()
        ]
        if meaningful_cats and coin.get("track_name") in ["待深度背调验真", "全网热搜异动榜", ""]:
            coin["track_name"] = meaningful_cats[0][:22]

    # Step 3: DexScreener 链上数据补全（如果缺少链上流动性或买卖比）
    if float(coin.get("liquidity_usd") or 0) == 0 or not coin.get("dex_url"):
        try:
            q = contract_addr if contract_addr else symbol
            d_resp = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={q}", timeout=10)
            if d_resp.status_code == 200:
                pairs = d_resp.json().get("pairs") or []
                matching_pairs = [
                    p
                    for p in pairs
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
                    tx24 = (best_p.get("txns") or {}).get("h24") or {}
                    b24 = int(tx24.get("buys") or 0)
                    s24 = int(tx24.get("sells") or 0)
                    if b24 + s24 > 0 and coin.get("buys_24h", 0) == 0:
                        coin["buys_24h"] = b24
                        coin["sells_24h"] = s24
                        coin["buy_ratio"] = round((b24 / (b24 + s24)) * 100, 1)
        except Exception:
            pass

    # Step 4: Tavily 实时全网搜索背调（融资背景 + 近期催化剂）
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
# 双轨量化评分系统：Meme 专属链上评分 vs 价值叙事项目评分
# ==============================================================================
def calculate_quant_score(coin, track_heat_score, weights):
    mc = float(coin.get("market_cap") or 1)
    fdv = float(coin.get("fully_diluted_valuation") or mc)
    vol = float(coin.get("total_volume") or 0)
    chg_1h = float(coin.get("price_change_1h") or 0)
    chg_24h = float(coin.get("price_change_percentage_24h") or 0)
    ath_drop = float(coin.get("ath_change_percentage") or -50)
    liq = float(coin.get("liquidity_usd") or 0)
    buy_ratio = float(coin.get("buy_ratio") or 50.0)
    commits = int(coin.get("commits_4w") or 0)
    vc_hits = coin.get("vc_hits") or []

    turnover = vol / mc if mc > 0 else 0
    mc_fdv_ratio = mc / fdv if fdv > 0 else 1.0

    if coin.get("is_meme_candidate"):
        # 🐶 链上 Meme 专属评分公式
        if liq >= 200_000:
            liq_score = 95
        elif liq >= 80_000:
            liq_score = 85
        elif liq >= 40_000:
            liq_score = 72
        else:
            liq_score = 65

        buy_bonus = min(max((buy_ratio - 48.0) * 3.5, 0), 30)
        mom_score = min(65 + buy_bonus + (10 if chg_1h > 2 else 0), 98)

        if turnover >= 0.8:
            vel_score = 95
        elif turnover >= 0.35:
            vel_score = 86
        elif turnover >= 0.15:
            vel_score = 75
        else:
            vel_score = 60

        if 500_000 <= mc <= 25_000_000:
            odds_score = 95
        elif 25_000_000 < mc <= 60_000_000:
            odds_score = 84
        else:
            odds_score = 72

        quant_total = liq_score * 0.25 + mom_score * 0.30 + vel_score * 0.25 + odds_score * 0.20
    else:
        # 🚀 叙事黑马 / 赛道龙头 / 底部价值评分公式
        opp_type = coin.get("initial_opp_type", "")
        if "底部价值" in opp_type:
            drop_score = min(max((abs(ath_drop) - 40) * 1.5, 50), 95)
            safety_score = drop_score * 0.5 + min(mc_fdv_ratio * 100, 100) * 0.5
        else:
            mom_base = min(max(65 + chg_24h * 1.2, 55), 96)
            turn_base = min(max(turnover * 220, 60), 96)
            safety_score = mom_base * 0.55 + turn_base * 0.45

        tech_score = min(55 + commits * 3, 95) if commits > 0 else 65
        vc_score = min(65 + len(vc_hits) * 15, 98) if vc_hits else 68

        if 2_000_000 <= mc <= 50_000_000:
            mc_score = 95
        elif 50_000_000 < mc <= 150_000_000:
            mc_score = 85
        else:
            mc_score = 72

        quant_total = (
            track_heat_score * weights.get("track_heat", 0.25)
            + safety_score * weights.get("price_safety", 0.25)
            + tech_score * weights.get("tech_strength", 0.20)
            + vc_score * weights.get("marketing_vc", 0.15)
            + mc_score * weights.get("mc_odds", 0.15)
        )

    return round(quant_total, 1), round(mc_fdv_ratio * 100, 1), round(turnover * 100, 1)


def run_job2():
    print("🚀 [Job 2 V5.0] 启动三大早期捕获引擎 + 强制深度背调系统...")
    db = FeishuDB()
    weights = db.get_strategy_weights()
    local_data = notifier.load_local_db()

    approved_tracks = db.get_approved_tracks()
    if not approved_tracks:
        approved_tracks = local_data.get("tracks", [])

    candidate_pool = []
    seen_keys = set()

    # 1. 启动【引擎 1：链上早期 Meme / 金狗狙击】
    for m_coin in fetch_onchain_meme_candidates():
        key = (m_coin.get("symbol") or "").lower()
        if key and key not in seen_keys:
            seen_keys.add(key)
            m_coin["track_heat"] = 92
            candidate_pool.append(m_coin)

    # 2. 启动【引擎 2：全网叙事异动黑马（严控市值 < $3亿）】
    for n_coin in fetch_narrative_breakout_candidates(max_mc_usd=300_000_000):
        key = (n_coin.get("symbol") or "").lower()
        if key and key not in seen_keys:
            seen_keys.add(key)
            n_coin["track_heat"] = 88
            candidate_pool.append(n_coin)

    # 3. 启动【引擎 3：重点赛道龙头与底部价值潜伏】（兼容中英文键名）
    for track in approved_tracks[:4]:
        t_id = track.get("id") or track.get("赛道ID") or ""
        t_name = track.get("name") or track.get("赛道名称") or t_id
        if not t_id or t_id == "trending-meme":
            continue
        t_change = float(track.get("change_24h") or track.get("24h涨幅(%)") or 0)
        t_heat = min(max(72 + t_change * 2.5, 65), 96)

        print(f"🔎 正在深挖赛道: {t_name} ({t_id})...")
        t_coins = fetch_sector_alpha_candidates(
            t_id, t_name, min_mc_usd=1_500_000, max_mc_usd=300_000_000
        )
        for c in t_coins:
            key = (c.get("symbol") or "").lower()
            if key and key not in seen_keys:
                seen_keys.add(key)
                c["track_heat"] = t_heat
                candidate_pool.append(c)
        time.sleep(1.2)

    print(f"📊 三大引擎初筛共汇总 {len(candidate_pool)} 个早期高潜力候选标的，开始执行【强制深度背调】...")

    selected_projects = []
    tz_bj = timezone(timedelta(hours=8))
    now_str = datetime.now(tz_bj).strftime("%Y-%m-%d %H:%M")

    for coin in candidate_pool[:12]:
        sym = (coin.get("symbol") or "").upper()
        print(f"🕵️‍♂️ 正在深度背调: ${sym} ({coin.get('name')})...")
        coin = conduct_deep_research(coin)

        if is_excluded_token(
            coin.get("coingecko_id"), sym, coin.get("name"), coin.get("market_cap"), max_mc_usd=350_000_000
        ):
            print(f"   ⏭️ ${sym} 经背调属于大市值老币或稳定衍生品，已剔除")
            continue

        quant_score, mc_fdv_pct, turnover_pct = calculate_quant_score(
            coin, coin.get("track_heat", 80), weights
        )
        if quant_score < 62:
            continue

        dossier = {
            "symbol": sym,
            "name": coin.get("name"),
            "chain": coin.get("chain", "MULTI"),
            "is_meme_candidate": coin.get("is_meme_candidate", False),
            "initial_opp_type": coin.get("initial_opp_type"),
            "coingecko_categories": coin.get("real_categories", []),
            "description": coin.get("description_en", "暂无简介"),
            "price_usd": coin.get("current_price"),
            "change_1h_pct": round(float(coin.get("price_change_1h") or 0), 2),
            "change_24h_pct": round(float(coin.get("price_change_percentage_24h") or 0), 2),
            "market_cap_wan_usd": round(float(coin.get("market_cap") or 0) / 10000, 1),
            "liquidity_wan_usd": round(float(coin.get("liquidity_usd") or 0) / 10000, 1),
            "turnover_24h_pct": turnover_pct,
            "mc_fdv_ratio_pct": mc_fdv_pct,
            "onchain_buys_24h": coin.get("buys_24h", 0),
            "onchain_sells_24h": coin.get("sells_24h", 0),
            "onchain_buy_ratio_pct": coin.get("buy_ratio", 50.0),
            "github_commits_4w": coin.get("commits_4w", 0),
            "vc_endorsements": coin.get("vc_hits", []),
            "latest_news_catalysts": coin.get("news_snippets", []),
            "quant_score": quant_score,
        }

        ai_score, debate_report, verified_type, verified_track, catalyst = multi_agent_evaluate(dossier)
        final_score = round(quant_score * 0.55 + ai_score * 0.45, 1)

        if final_score >= 66:
            final_track = verified_track or coin.get("track_name") or "早期叙事Alpha"
            p_data = {
                "id": coin.get("id"),
                "coingecko_id": coin.get("coingecko_id") or "",
                "symbol": sym,
                "name": coin.get("name"),
                "chain": coin.get("chain", "MULTI"),
                "contract_address": coin.get("contract_address", ""),
                "opp_type": verified_type,
                "track": final_track,
                "catalyst": catalyst,
                "price": coin.get("current_price"),
                "change_1h": round(float(coin.get("price_change_1h") or 0), 2),
                "change_24h": round(float(coin.get("price_change_percentage_24h") or 0), 2),
                "change_7d": round(float(coin.get("price_change_percentage_7d_in_currency") or 0), 2),
                "turnover_24h": turnover_pct,
                "market_cap": round(float(coin.get("market_cap") or 0) / 10000, 2),
                "liquidity_wan": round(float(coin.get("liquidity_usd") or 0) / 10000, 2),
                "buys_24h": coin.get("buys_24h", 0),
                "sells_24h": coin.get("sells_24h", 0),
                "buy_ratio": coin.get("buy_ratio", 50.0),
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
            print(f"   ✅ 入选! ${sym} | 类型: {verified_type} | 赛道: {final_track} | 综合得分: {final_score}")
        time.sleep(1.2)

    # 重新读取最新本地库，按综合得分排序并更新项目池
    latest_local = notifier.load_local_db()
    selected_projects.sort(key=lambda x: x["final_score"], reverse=True)
    if selected_projects:
        # 将本轮新入选项目置顶，并合并历史优质早期项目（自动剔除旧的大市值白马与重复项）
        merged = list(selected_projects)
        existing_syms = {p["symbol"].upper() for p in merged}
        for old_p in latest_local.get("projects", []):
            old_sym = str(old_p.get("symbol", "")).upper()
            old_mc_usd = float(old_p.get("market_cap") or 0) * 10000
            if (
                old_sym
                and old_sym not in existing_syms
                and not is_excluded_token(old_p.get("id", ""), old_sym, old_p.get("name", ""), old_mc_usd)
            ):
                existing_syms.add(old_sym)
                merged.append(old_p)
        latest_local["projects"] = merged[:18]
        notifier.save_local_db(latest_local)

    notifier.send_wechat(
        "🎯 [Alpha 狙击战报] 早期项目深度背调完成",
        f"本轮共严选出 {len(selected_projects)} 个早期高赔率项目",
    )


if __name__ == "__main__":
    run_job2()
