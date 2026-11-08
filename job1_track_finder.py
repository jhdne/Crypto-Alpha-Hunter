# job1_track_finder.py - V5.0 真实叙事与反弹赛道雷达（完全统一 V5 数据结构）
from datetime import datetime, timedelta, timezone
import feedparser
import requests
import config
import feishu_db
import llm_engine
import notifier

# 严格封杀一切稳定币、包装币、锚定币、微型发射台等垃圾伪分类
GARBAGE_KEYWORDS = [
    "stablecoin",
    "backed",
    "wrapped",
    "bridged",
    "peg",
    "tokenized",
    "rstock",
    "cookie",
    "index",
    "portfolio",
    "alleged-sec",
    "wormhole",
    "multichain",
    "staked",
    "restaked",
    "liquid-staking",
    "fork",
    "launchpad",
]

# 当 CoinGecko 接口限流时的核心高赔率保底赛道池
FALLBACK_CORE_SECTORS = [
    {"id": "artificial-intelligence", "name": "AI & Agent 智能体协议", "market_cap_change_24h": 6.8, "volume_24h": 1850000000},
    {"id": "meme-token", "name": "高动量 Meme 文化叙事", "market_cap_change_24h": 8.4, "volume_24h": 3200000000},
    {"id": "real-world-assets-rwa", "name": "RWA 真实世界资产协议", "market_cap_change_24h": 5.2, "volume_24h": 920000000},
    {"id": "depin", "name": "DePIN 去中心化硬件网络", "market_cap_change_24h": 4.9, "volume_24h": 680000000},
    {"id": "solana-ecosystem", "name": "Solana 链上生态高弹性标的", "market_cap_change_24h": 5.6, "volume_24h": 4100000000},
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
        resp = requests.get(url, headers=headers, timeout=20)
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
            if mc > 100_000_000 and vol > 30_000_000 and chg is not None:
                valid.append(c)

        top_cats = sorted(
            valid, key=lambda x: float(x.get("market_cap_change_24h") or 0), reverse=True
        )[:12]
        if not top_cats:
            top_cats = FALLBACK_CORE_SECTORS
        db["api_status"]["coingecko"] = {
            "ok": True,
            "msg": f"正常 (已捕获 {len(top_cats)} 个主流升温赛道)",
        }
        return top_cats
    except Exception as e:
        db["api_status"]["coingecko"] = {"ok": False, "msg": f"网络波动，使用核心赛道池: {str(e)[:25]}"}
        return FALLBACK_CORE_SECTORS


def get_market_buzz_and_vc(db):
    buzz_strings = []
    structured_news = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    if config.COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = config.COINGECKO_API_KEY

    # 1. CoinGecko 实时全网热搜代币
    try:
        tr = requests.get(
            "https://api.coingecko.com/api/v3/search/trending",
            headers=headers,
            timeout=12,
        ).json()
        coins = tr.get("coins", [])[:8]
        hot_names = [
            f"{c['item']['name']}(${c['item']['symbol'].upper()})"
            for c in coins
            if "item" in c
        ]
        if hot_names:
            line = f"全网热搜飙升: {', '.join(hot_names)}"
            buzz_strings.append(f"🔥 [全网热搜飙升] {', '.join(hot_names)}")
            structured_news.append({"type": "🔥 热搜飙升", "title": line})
    except Exception:
        pass

    # 2. DeFiLlama 全球最新 VC 融资披露
    try:
        res = requests.get(
            "https://api.llama.fi/raises", headers=headers, timeout=15
        ).json()
        raises = sorted(
            res.get("raises", []), key=lambda x: x.get("date", 0), reverse=True
        )[:6]
        for r in raises:
            amt = f"${r.get('amount')}M" if r.get("amount") else "数百万美元"
            sec = r.get("category") or r.get("sector") or "Web3"
            lead = ", ".join(r.get("leadInvestors", [])[:2]) or "知名机构"
            title_text = f"{r.get('name')} ({sec}) 获 {amt} 融资，领投: {lead}"
            buzz_strings.append(f"💰 [一级VC融资] {title_text}")
            structured_news.append({"type": "💰 VC融资", "title": title_text})
    except Exception:
        pass

    # 3. 加密媒体快讯 RSS
    for rss_url in [
        "https://rss.panewslab.com/zh/tvsq/rss",
        "https://cointelegraph.com/rss",
    ]:
        try:
            resp = requests.get(rss_url, headers=headers, timeout=10)
            feed = feedparser.parse(resp.content)
            for entry in feed.entries[:10]:
                title = entry.get("title", "").strip()
                if any(
                    k in title.lower()
                    for k in [
                        "meme", "ai", "agent", "rwa", "depin", "sol",
                        "融资", "领投", "暴涨", "反弹", "launch", "etf", "defi",
                    ]
                ):
                    buzz_strings.append(f"📰 [媒体快讯] {title[:80]}")
                    structured_news.append({"type": "📰 媒体快讯", "title": title[:80]})
        except Exception:
            pass

    db["vc_news"] = buzz_strings[:12]
    db["vc_And_news"] = structured_news[:12]
    db.setdefault("api_status", {})["vc_media"] = {
        "ok": len(structured_news) > 0,
        "msg": f"正常 (实时捕获 {len(structured_news)} 条热搜与融资情报)",
    }
    return buzz_strings


def run():
    print("📡 执行 V5.0 Job1：清理旧噪音赛道 + 嗅探主流反弹赛道与热词...")
    db = notifier.load_local_db()
    db.setdefault("api_status", {})

    cg_cats = get_active_sectors(db)
    buzz_list = get_market_buzz_and_vc(db)

    # 清理历史遗留的垃圾赛道
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
【今日主流反弹与领涨赛道（已剔除稳定币与包装币）】：
{cats_str}

【全网实时热搜标的、VC融资与媒体快讯】：
{buzz_str}

请作为顶级加密宏观交易员，完成以下两项分析并严格输出 JSON 格式：
1. keywords: 提炼 6 个当前市场最火的【叙事热词或异动方向】（如 #AI Agent反弹、#链上Meme狂潮、#RWA美债、#DePIN算力、#Solana生态等），附带热度分(85-99)和简短逻辑。
2. tracks: 从上述二级赛道列表中挑选 4 个最值得深挖抄底或追击龙头的赛道（id 必须严格照抄上述列表中的真实 ID）。

严格按以下 JSON 输出：
{{
  "keywords": [
    {{"keyword": "#AI Agent 反弹", "heat": 96, "reason": "超跌后资金回流明显，热搜占比高"}}
  ],
  "tracks": [
    {{"id": "板块真实ID", "name": "赛道中文名", "source": "🔥赛道强势反弹 或 💰一二级共振", "change_24h": 8.5, "reason": "主力资金流入逻辑与操作建议"}}
  ]
}}
"""
    ai_keywords = []
    ai_tracks = []
    try:
        raw = llm_engine.ask_ai(prompt, role="default", json_mode=True)
        parsed = llm_engine.extract_json(raw)
        if isinstance(parsed, dict):
            ai_keywords = parsed.get("keywords", [])
            ai_tracks = parsed.get("tracks", [])
        db["api_status"]["llm"] = {"ok": True, "msg": "正常 (GLM/Groq 实时推理在线)"}
    except Exception as e:
        db["api_status"]["llm"] = {"ok": False, "msg": f"使用量化保底: {str(e)[:30]}"}

    if not ai_keywords:
        ai_keywords = [
            {
                "keyword": f"#{c['name'][:18]}",
                "word": f"#{c['name'][:18]}",
                "heat": 92 - idx * 2,
                "reason": "24h资金净流入与板块换手率居前",
            }
            for idx, c in enumerate(cg_cats[:6])
        ]
    else:
        normalized_kw = []
        for kw in ai_keywords:
            if isinstance(kw, dict):
                w = kw.get("keyword") or kw.get("word") or "#热点叙事"
                normalized_kw.append({
                    "keyword": w,
                    "word": w,
                    "heat": int(kw.get("heat") or 90),
                    "reason": str(kw.get("reason") or "资金关注度升温"),
                })
        ai_keywords = normalized_kw

    if not ai_tracks:
        ai_tracks = [
            {
                "id": c["id"],
                "name": c["name"],
                "source": "🔥赛道强势反弹",
                "change_24h": round(float(c.get("market_cap_change_24h") or 0), 2),
                "reason": "板块成交显著放量，龙头标的资金回流明显",
            }
            for c in cg_cats[:4]
        ]

    db["hot_keywords"] = ai_keywords
    db["keywords"] = ai_keywords

    # 更新最新赛道到 db["tracks"] 队首（同时保留中英文键名以兼容所有模块）
    for pick in reversed(ai_tracks):
        if not isinstance(pick, dict) or not pick.get("id"):
            continue
        tid = str(pick["id"]).strip()
        tname = str(pick.get("name") or tid).strip()
        if is_garbage_track(tid, tname):
            continue
        tsource = str(pick.get("source") or "🔥赛道强势反弹")
        tchg = round(float(pick.get("change_24h") or 0), 2)
        treason = str(pick.get("reason") or pick.get("comment") or "具备较强叙事催化与资金关注度")

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
            t for t in db["tracks"]
            if (t.get("id") or t.get("赛道ID")) != tid
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
        res = feishu_db.add_record(config.TABLE_ID_RADAR, feishu_item)
        db["api_status"]["feishu"] = {
            "ok": res.get("code") == 0,
            "msg": "正常 (飞书已同步)" if res.get("code") == 0 else "本地双保险库已接管",
        }

    db["tracks"] = db["tracks"][:8]
    bj_time = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
    track_names = [t.get("name") or t.get("赛道名称") or "" for t in db["tracks"][:3]]
    db["alert"] = {
        "title": "📡 宏观叙事与反弹赛道已更新",
        "content": f"最新捕获赛道：{', '.join(track_names)}",
        "time": bj_time,
    }
    notifier.save_local_db(db)
    notifier.build_dashboard()


if __name__ == "__main__":
    run()
