# job1_track_finder.py - V7.0 趋势推演、多维资金面嗅探与龙头/黑马配置清单
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import feedparser
import requests
import config
import feishu_db
import llm_engine
import notifier
from logger import get_logger

log = get_logger("job1_track_finder")
_SESSION = requests.Session()

GARBAGE_KEYWORDS = [
    "stablecoin", "backed", "wrapped", "bridged", "peg", "tokenized",
    "rstock", "cookie", "index", "portfolio", "alleged-sec", "wormhole",
    "multichain", "staked", "restaked", "liquid-staking", "fork", "launchpad",
]

FALLBACK_CORE_SECTORS = [
    {"id": "artificial-intelligence", "name": "AI & Agent 智能体协议", "market_cap_change_24h": 6.8, "volume_24h": 1850000000},
    {"id": "meme-token", "name": "链上早期 Meme 文化叙事", "market_cap_change_24h": 8.4, "volume_24h": 3200000000},
    {"id": "real-world-assets-rwa", "name": "RWA 真实世界资产协议", "market_cap_change_24h": 5.2, "volume_24h": 920000000},
    {"id": "depin", "name": "DePIN 去中心化硬件网络", "market_cap_change_24h": 4.9, "volume_24h": 680000000},
    {"id": "solana-ecosystem", "name": "Solana 链上高弹性生态", "market_cap_change_24h": 5.6, "volume_24h": 4100000000},
    {"id": "decentralized-finance-defi", "name": "DeFi 新一代收益与衍生品", "market_cap_change_24h": 4.1, "volume_24h": 2400000000},
]


def is_garbage_track(cat_id, cat_name=""):
    text = f"{cat_id} {cat_name}".lower()
    return any(k in text for k in GARBAGE_KEYWORDS)


def get_active_sectors(db):
    url = "https://api.coingecko.com/api/v3/coins/categories"
    headers = {"accept": "application/json", "User-Agent": "Mozilla/5.0"}
    if config.COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = config.COINGECKO_API_KEY

    db.setdefault("api_status", {})
    try:
        resp = _SESSION.get(url, headers=headers, timeout=20)
        res = resp.json() if resp.status_code == 200 else None
        if not isinstance(res, list):
            db["api_status"]["coingecko"] = {"ok": False, "msg": "接口限流，已启用核心高弹性赛道池"}
            return FALLBACK_CORE_SECTORS

        valid = []
        for c in res:
            if not isinstance(c, dict):
                continue
            cid = str(c.get("id", ""))
            cname = str(c.get("name", ""))
            if is_garbage_track(cid, cname):
                continue
            mc = float(c.get("market_cap") or 0)
            vol = float(c.get("volume_24h") or 0)
            chg = c.get("market_cap_change_24h")
            if mc > 80_000_000 and vol > 25_000_000 and chg is not None and -3.0 <= float(chg) <= 35.0:
                valid.append(c)

        top_cats = sorted(
            valid, key=lambda x: float(x.get("market_cap_change_24h") or 0), reverse=True
        )[:12]
        if not top_cats:
            top_cats = FALLBACK_CORE_SECTORS
        db["api_status"]["coingecko"] = {
            "ok": True,
            "msg": f"正常 (已捕获 {len(top_cats)} 个早期轮动升温赛道)",
        }
        return top_cats
    except Exception as e:
        log.warning("CoinGecko 赛道获取异常: %s", e)
        db["api_status"]["coingecko"] = {"ok": False, "msg": f"网络波动，使用核心赛道池: {str(e)[:25]}"}
        return FALLBACK_CORE_SECTORS


def _fetch_cg_trending(headers):
    buzz, structured, symbols = [], [], []
    try:
        tr = _SESSION.get(
            "https://api.coingecko.com/api/v3/search/trending",
            headers=headers,
            timeout=12,
        ).json()
        coins = tr.get("coins", [])[:8]
        hot_names = []
        for c in coins:
            item = c.get("item")
            if item:
                sym = str(item.get("symbol", "")).upper()
                symbols.append(sym)
                hot_names.append(f"{item.get('name')}(${sym})")
        if hot_names:
            line = f"全网热搜飙升: {', '.join(hot_names)}"
            buzz.append(f"🔥 [全网热搜飙升] {', '.join(hot_names)}")
            structured.append({"type": "🔥 热搜飙升", "title": line})
    except Exception as e:
        log.debug("CoinGecko trending 获取异常: %s", e)
    return buzz, structured, symbols


def _fetch_llama_raises(headers):
    buzz, structured, vc_entities = [], [], []
    try:
        res = _SESSION.get("https://api.llama.fi/raises", headers=headers, timeout=15).json()
        raises = sorted(
            res.get("raises", []), key=lambda x: x.get("date", 0), reverse=True
        )[:8]
        for r in raises:
            name = str(r.get("name", "")).strip()
            amt = f"${r.get('amount')}M" if r.get("amount") else "数百万美元"
            sec = r.get("category") or r.get("sector") or "Web3"
            lead = ", ".join(r.get("leadInvestors", [])[:2]) or "知名机构"
            title_text = f"{name} ({sec}) 获 {amt} 融资，领投: {lead}"
            buzz.append(f"💰 [一级VC融资] {title_text}")
            structured.append({"type": "💰 VC融资", "title": title_text})
            if name:
                vc_entities.append(name.lower())
    except Exception as e:
        log.debug("DeFiLlama raises 获取异常: %s", e)
    return buzz, structured, vc_entities


def _fetch_llama_tvl_growth(headers):
    """V7.0 新增：捕获 DeFiLlama 7日 TVL 净流入最快的新锐协议"""
    buzz, structured = [], []
    try:
        protocols = _SESSION.get("https://api.llama.fi/protocols", headers=headers, timeout=15).json()
        if isinstance(protocols, list):
            rising = [
                p for p in protocols
                if 5_000_000 <= float(p.get("tvl") or 0) <= 200_000_000
                and float(p.get("change_7d") or 0) >= 25.0
            ]
            rising.sort(key=lambda x: float(x.get("change_7d") or 0), reverse=True)
            for p in rising[:4]:
                chg7 = float(p.get("change_7d") or 0)
                tvl_m = float(p.get("tvl") or 0) / 1e6
                title_text = f"{p.get('name')} ({p.get('category', 'DeFi')}) TVL 7日激增 +{chg7:.1f}% 至 ${tvl_m:.1f}M"
                buzz.append(f"🌊 [链上TVL异动] {title_text}")
                structured.append({"type": "🌊 TVL异动", "title": title_text})
    except Exception as e:
        log.debug("DeFiLlama protocols 获取异常: %s", e)
    return buzz, structured, []


def _fetch_rss(rss_url, headers):
    buzz, structured = [], []
    keywords = [
        "meme", "ai", "agent", "rwa", "depin", "sol",
        "融资", "领投", "暴涨", "反弹", "launch", "etf", "defi",
    ]
    try:
        resp = _SESSION.get(rss_url, headers=headers, timeout=10)
        feed = feedparser.parse(resp.content)
        for entry in feed.entries[:10]:
            title = entry.get("title", "").strip()
            if any(k in title.lower() for k in keywords):
                buzz.append(f"📰 [媒体快讯] {title[:80]}")
                structured.append({"type": "📰 媒体快讯", "title": title[:80]})
    except Exception as e:
        log.debug("RSS (%s) 获取异常: %s", rss_url, e)
    return buzz, structured, []


def get_market_buzz_and_vc(db):
    buzz_strings = []
    structured_news = []
    trending_symbols = []
    vc_entities = []

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    if config.COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = config.COINGECKO_API_KEY

    rss_urls = [
        "https://rss.panewslab.com/zh/tvsq/rss",
        "https://cointelegraph.com/rss",
    ]

    with ThreadPoolExecutor(max_workers=5) as pool:
        f_trend = pool.submit(_fetch_cg_trending, headers)
        f_raises = pool.submit(_fetch_llama_raises, headers)
        f_tvl = pool.submit(_fetch_llama_tvl_growth, headers)
        f_rss = [pool.submit(_fetch_rss, url, headers) for url in rss_urls]

        b, s, syms = f_trend.result()
        buzz_strings.extend(b)
        structured_news.extend(s)
        trending_symbols.extend(syms)

        b, s, vcs = f_raises.result()
        buzz_strings.extend(b)
        structured_news.extend(s)
        vc_entities.extend(vcs)

        b, s, _ = f_tvl.result()
        buzz_strings.extend(b)
        structured_news.extend(s)

        for fut in f_rss:
            b, s, _ = fut.result()
            buzz_strings.extend(b)
            structured_news.extend(s)

    db["vc_news"] = buzz_strings[:14]
    db["vc_And_news"] = structured_news[:14]
    db["trending_symbols"] = list(dict.fromkeys(trending_symbols))
    db["vc_entities"] = list(dict.fromkeys(vc_entities))
    db.setdefault("api_status", {})["vc_media"] = {
        "ok": len(structured_news) > 0,
        "msg": f"正常 (实时捕获 {len(structured_news)} 条热搜、TVL与融资情报)",
    }
    return buzz_strings


def run():
    log.info("执行 V7.0 Job1：趋势推演、多维资金面嗅探与龙头/黑马配置清单...")
    db = notifier.load_local_db()
    db.setdefault("api_status", {})

    cg_cats = get_active_sectors(db)
    buzz_list = get_market_buzz_and_vc(db)

    existing_tracks = db.get("tracks", [])
    clean_existing = []
    for t in existing_tracks:
        tid = t.get("id") or t.get("赛道ID") or ""
        tname = t.get("name") or t.get("赛道名称") or ""
        if tid and not is_garbage_track(tid, tname):
            clean_existing.append(t)
    db["tracks"] = clean_existing

    cats_str = "\n".join([
        f"- ID: {c['id']} | 名称: {c['name']} | 24h涨幅: {float(c.get('market_cap_change_24h') or 0):.2f}% | 24h成交额: ${float(c.get('volume_24h') or 0)/1e6:.0f}M"
        for c in cg_cats
    ])
    buzz_str = "\n".join(buzz_list)

    prompt = f"""
【今日资金刚启动/轮动升温的主流赛道（已剔除稳定币与包装币）】：
{cats_str}

【全网实时热搜标的、TVL资金异动、VC融资与媒体快讯】：
{buzz_str}

请作为全周期加密宏观猎手，完成趋势推演与前瞻配置输出，严格返回 JSON：
1. keywords: 提炼 6 个当前最具爆发潜力的叙事热词（附热度 85-99 与介入逻辑）。
2. tracks: 从上述赛道列表中挑选 4 个最值得布局的赛道（id 严格照抄真实 ID）。
3. allocation_matrix: 为上述挑选的 4 个核心赛道，分别给出前瞻配置清单：高确定性「龙头标的 (leader)」与高弹性「黑马标的 (dark_horse)」方向及配置比例建议。

严格按以下 JSON 输出：
{{
  "keywords": [
    {{"keyword": "#AI Agent 早期协议", "heat": 96, "reason": "一级VC密集注资，链上小市值Agent代币刚放量点火"}}
  ],
  "tracks": [
    {{"id": "板块真实ID", "name": "赛道中文名", "source": "🔥早期资金点火 或 💰一二级共振", "change_24h": 6.5, "reason": "主力资金刚开始流入该板块小市值标的，具备早期埋伏价值"}}
  ],
  "allocation_matrix": [
    {{
      "track": "赛道中文名",
      "trend_thesis": "一句话趋势推演逻辑",
      "leader": "龙头代表方向/代币（如 FET / VIRTUAL）",
      "dark_horse": "高弹性黑马方向（如 市值<$500万的Solana链上新Agent协议）",
      "ratio_hint": "龙头 60% / 黑马 40%"
    }}
  ]
}}
"""
    ai_keywords = []
    ai_tracks = []
    allocation_matrix = []
    try:
        raw = llm_engine.ask_ai(prompt, role="default", json_mode=True)
        parsed = llm_engine.extract_json(raw)
        if isinstance(parsed, dict):
            ai_keywords = parsed.get("keywords", [])
            ai_tracks = parsed.get("tracks", [])
            allocation_matrix = parsed.get("allocation_matrix", [])
            db["api_status"]["llm"] = {"ok": True, "msg": "正常 (GLM/Groq 实时推理在线)"}
        else:
            db["api_status"]["llm"] = {"ok": False, "msg": "LLM 返回为空，使用量化推演保底"}
    except Exception as e:
        log.warning("Job1 LLM 推理异常: %s", e)
        db["api_status"]["llm"] = {"ok": False, "msg": f"使用量化保底: {str(e)[:30]}"}

    if not ai_keywords:
        ai_keywords = [
            {
                "keyword": f"#{c['name'][:18]}",
                "word": f"#{c['name'][:18]}",
                "heat": 92 - idx * 2,
                "reason": "板块量能温和放大，早期资金净流入居前",
            }
            for idx, c in enumerate(cg_cats[:6])
        ]
    else:
        normalized_kw = []
        for kw in ai_keywords:
            if isinstance(kw, dict):
                w = kw.get("keyword") or kw.get("word") or "#早期热点叙事"
                normalized_kw.append({
                    "keyword": w,
                    "word": w,
                    "heat": int(kw.get("heat") or 90),
                    "reason": str(kw.get("reason") or "早期资金关注度升温"),
                })
        ai_keywords = normalized_kw

    if not ai_tracks:
        ai_tracks = [
            {
                "id": c["id"],
                "name": c["name"],
                "source": "🔥早期资金点火",
                "change_24h": round(float(c.get("market_cap_change_24h") or 0), 2),
                "reason": "板块成交放量启动，中小市值标的弹性极佳",
            }
            for c in cg_cats[:4]
        ]

    if not allocation_matrix:
        allocation_matrix = [
            {
                "track": str(t.get("name") or t.get("id")),
                "trend_thesis": str(t.get("reason") or "板块量价温和启动，一二级资金共振"),
                "leader": f"{t.get('name', '该赛道')} 头部高流动性核心协议",
                "dark_horse": f"市值 <$500万 且买盘占比 >55% 的早期新池标的",
                "ratio_hint": "龙头 55% / 黑马 45%",
            }
            for t in ai_tracks[:4]
            if isinstance(t, dict)
        ]

    db["hot_keywords"] = ai_keywords
    db["keywords"] = ai_keywords
    db["allocation_matrix"] = allocation_matrix[:6]

    for pick in reversed(ai_tracks):
        if not isinstance(pick, dict) or not pick.get("id"):
            continue
        tid = str(pick["id"]).strip()
        tname = str(pick.get("name") or tid).strip()
        if is_garbage_track(tid, tname):
            continue
        tsource = str(pick.get("source") or "🔥早期资金点火")
        tchg = round(float(pick.get("change_24h") or 0), 2)
        treason = str(pick.get("reason") or pick.get("comment") or "具备早期叙事催化与资金关注度")

        unified_track = {
            "id": tid,
            "name": tname,
            "source": tsource,
            "change_24h": tchg,
            "reason": treason,
            "status": "已批准",
            "赛道ID": tid,
            "赛道名称": tname,
            "发现来源": tsource,
            "24h涨幅(%)": tchg,
            "AI赛道简评": treason,
            "人工状态": "允许深挖",
        }
        db["tracks"] = [
            t for t in db["tracks"] if (t.get("id") or t.get("赛道ID")) != tid
        ]
        db["tracks"].insert(0, unified_track)

        feishu_item = {
            "赛道ID": tid,
            "赛道名称": tname,
            "发现来源": tsource,
            "24h涨幅(%)": tchg,
            "AI赛道简评": treason,
            "人工状态": "允许深挖",
        }
        feishu_ok = feishu_db.add_record(config.TABLE_ID_RADAR, feishu_item)
        db["api_status"]["feishu"] = {
            "ok": bool(feishu_ok),
            "msg": "正常 (飞书已同步)" if feishu_ok else "本地双保险库已接管",
        }

    db["tracks"] = db["tracks"][:8]
    bj_time = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
    track_names = [t.get("name") or t.get("赛道名称") or "" for t in db["tracks"][:3]]
    db["alert"] = {
        "title": "📡 趋势推演与龙头/黑马配置清单已更新",
        "content": f"最新捕获赛道：{', '.join(track_names)}",
        "time": bj_time,
    }
    notifier.save_local_db(db)
    notifier.build_dashboard(db["alert"]["title"], db["alert"]["content"])


if __name__ == "__main__":
    run()
