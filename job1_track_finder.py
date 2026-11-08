# job1_track_finder.py - V4.0 真实叙事与反弹赛道雷达
from datetime import datetime, timedelta, timezone
import json
import os
import config
import feedparser
import feishu_db
import llm_engine
import notifier
import requests

DB_FILE = "docs/alpha_db.json"

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


def load_db():
  os.makedirs("docs", exist_ok=True)
  if os.path.exists(DB_FILE):
    try:
      with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)
    except Exception:
      pass
  return {
      "api_status": {},
      "keywords": [],
      "vc_news": [],
      "tracks": [],
      "projects": [],
      "alert": {},
  }


def save_db(db):
  os.makedirs("docs", exist_ok=True)
  with open(DB_FILE, "w", encoding="utf-8") as f:
    json.dump(db, f, ensure_ascii=False, indent=2)


def is_garbage_track(cat_id, cat_name=""):
  text = f"{cat_id} {cat_name}".lower()
  return any(k in text for k in GARBAGE_KEYWORDS)


def get_active_sectors(db):
  url = "https://api.coingecko.com/api/v3/coins/categories"
  headers = {"accept": "application/json", "User-Agent": "Mozilla/5.0"}
  if config.COINGECKO_API_KEY:
    headers["x-cg-demo-api-key"] = config.COINGECKO_API_KEY

  try:
    res = requests.get(url, headers=headers, timeout=20).json()
    if not isinstance(res, list):
      db["api_status"]["coingecko"] = {"ok": False, "msg": "接口限流，使用核心赛道池"}
      return []

    valid = []
    for c in res:
      if not isinstance(c, dict):
        continue
      cid = str(c.get("id", ""))
      cname = str(c.get("name", ""))
      if is_garbage_track(cid, cname):
        continue
      # 必须具备真实市场厚度：总市值 > 1亿美金 且 24h成交量 > 3000万美金
      mc = float(c.get("market_cap") or 0)
      vol = float(c.get("volume_24h") or 0)
      chg = c.get("market_cap_change_24h")
      if mc > 100000000 and vol > 30000000 and chg is not None:
        valid.append(c)

    # 按 24h 涨幅排序，捕捉正在强力反弹的主流赛道
    top_cats = sorted(
        valid, key=lambda x: x["market_cap_change_24h"], reverse=True
    )[:12]
    db["api_status"]["coingecko"] = {
        "ok": True,
        "msg": f"正常 (已捕获 {len(top_cats)} 个主流升温赛道)",
    }
    return top_cats
  except Exception as e:
    db["api_status"]["coingecko"] = {"ok": False, "msg": f"网络波动: {str(e)[:30]}"}
    return []


def get_market_buzz_and_vc(db):
  buzz_list = []
  headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

  # 1. CoinGecko 实时全网热搜代币 (散户与游资焦点)
  try:
    tr = requests.get(
        "https://api.coingecko.com/api/v3/search/trending",
        headers=headers,
        timeout=12,
    ).json()
    coins = tr.get("coins", [])[:8]
    hot_names = [
        f"{c['item']['name']}(${c['item']['symbol'].upper()})" for c in coins
    ]
    if hot_names:
      buzz_list.append(f"🔥 [全网热搜飙升] {', '.join(hot_names)}")
  except Exception:
    pass

  # 2. DeFiLlama 全球最新 VC 融资披露
  try:
    res = requests.get(
        "https://api.llama.fi/raises", headers=headers, timeout=15
    ).json()
    raises = sorted(
        res.get("raises", []), key=lambda x: x.get("date", 0), reverse=True
    )[:8]
    for r in raises:
      amt = f"${r.get('amount')}M" if r.get("amount") else "数百万美元"
      sec = r.get("category") or r.get("sector") or "Web3"
      lead = ", ".join(r.get("leadInvestors", [])[:2]) or "知名机构"
      buzz_list.append(
          f"💰 [一级VC融资] {r.get('name')} ({sec}) 获 {amt} 融资，领投: {lead}"
      )
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
      for entry in feed.entries[:12]:
        title = entry.get("title", "")
        if any(
            k in title.lower()
            for k in [
                "meme",
                "ai",
                "agent",
                "rwa",
                "depin",
                "sol",
                "融资",
                "领投",
                "暴涨",
                "反弹",
                "launch",
            ]
        ):
          buzz_list.append(f"📰 [媒体快讯] {title[:75]}")
    except Exception:
      pass

  db["vc_news"] = buzz_list[:12]
  db["api_status"]["vc_media"] = {
      "ok": len(buzz_list) > 0,
      "msg": f"正常 (实时捕获 {len(buzz_list)} 条热搜与融资情报)",
  }
  return buzz_list


def run():
  print("📡 执行 V4.0 Job1：清理旧垃圾赛道 + 嗅探主流反弹赛道与热词...")
  db = load_db()
  cg_cats = get_active_sectors(db)
  buzz_list = get_market_buzz_and_vc(db)

  # 清理历史遗留的垃圾赛道
  db["tracks"] = [
      t
      for t in db.get("tracks", [])
      if not is_garbage_track(t.get("赛道ID", ""), t.get("赛道名称", ""))
  ]

  cats_str = "\n".join([
      f"- ID: {c['id']} | 名称: {c['name']} | 24h涨幅:"
      f" {c['market_cap_change_24h']:.2f}% | 24h成交额:"
      f" ${c['volume_24h']/1e6:.0f}M"
      for c in cg_cats
  ])
  buzz_str = "\n".join(buzz_list)

  prompt = f"""
【今日主流反弹与领涨赛道（已剔除稳定币与包装币）】：
{cats_str}

【全网实时热搜标的、VC融资与媒体快讯】：
{buzz_str}

请作为顶级加密宏观交易员，完成以下两项分析并严格输出 JSON 格式：
1. keywords: 提炼 6 个当前市场最火的【叙事热词或异动方向】（如 Meme狂潮、AI Agent反弹、RWA、DePIN、Solana生态等），附带热度分(85-99)和简短逻辑。
2. tracks: 从上述二级赛道列表中挑选 4 个最值得深挖抄底或追击龙头的赛道（id 必须严格照抄上述列表中的真实 ID）。

严格按以下 JSON 输出：
{{
  "keywords": [
    {{"word": "#AI Agent 反弹", "heat": 96, "reason": "超跌后资金回流明显，热搜占比高"}}
  ],
  "tracks": [
    {{"id": "板块真实ID", "name": "赛道中文名", "source": "🔥赛道强势反弹 或 💰一二级共振", "change_24h": 8.5, "comment": "主力资金流入逻辑与操作建议"}}
  ]
}}
"""
  try:
    raw = llm_engine.ask_ai(prompt, role="default")
    parsed = llm_engine.extract_json(raw)
    ai_keywords = parsed.get("keywords", []) if isinstance(parsed, dict) else []
    ai_tracks = parsed.get("tracks", []) if isinstance(parsed, dict) else []
    db["api_status"]["llm"] = {"ok": True, "msg": "正常 (GLM/Groq 实时推理在线)"}
  except Exception as e:
    db["api_status"]["llm"] = {"ok": False, "msg": f"使用量化保底: {str(e)[:30]}"}
    ai_keywords = [
        {"word": f"#{c['name'][:16]}", "heat": 92, "reason": "24h资金净流入与涨幅居前"}
        for c in cg_cats[:6]
    ]
    ai_tracks = [
        {
            "id": c["id"],
            "name": c["name"],
            "source": "🔥赛道强势反弹",
            "change_24h": c["market_cap_change_24h"],
            "comment": "板块成交放量，龙头反弹明显",
        }
        for c in cg_cats[:4]
    ]

  if ai_keywords:
    db["keywords"] = ai_keywords

  # 更新最新赛道到 db["tracks"] 队首
  for pick in reversed(ai_tracks):
    if not isinstance(pick, dict) or "id" not in pick:
      continue
    if is_garbage_track(pick["id"], pick.get("name", "")):
      continue
    item = {
        "赛道ID": str(pick["id"]),
        "赛道名称": str(pick.get("name", pick["id"])),
        "发现来源": str(pick.get("source", "🔥赛道强势反弹")),
        "24h涨幅(%)": round(float(pick.get("change_24h") or 0), 2),
        "AI赛道简评": str(pick.get("comment", "")),
        "人工状态": "允许深挖",
    }
    db["tracks"] = [
        t for t in db["tracks"] if t.get("赛道ID") != item["赛道ID"]
    ]
    db["tracks"].insert(0, item)
    res = feishu_db.add_record(config.TABLE_ID_RADAR, item)
    db["api_status"]["feishu"] = {
        "ok": res.get("code") == 0,
        "msg": (
            "正常 (飞书已同步)" if res.get("code") == 0 else "本地双保险库已接管"
        ),
    }

  db["tracks"] = db["tracks"][:8]
  bj_time = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime(
      "%Y-%m-%d %H:%M"
  )
  db["alert"] = {
      "title": "📡 宏观叙事与反弹赛道已更新",
      "content": (
          "最新捕获赛道："
          f" {', '.join([t['赛道名称'] for t in db['tracks'][:3]])}"
      ),
      "time": bj_time,
  }
  save_db(db)
  notifier.build_dashboard()


if __name__ == "__main__":
  run()
