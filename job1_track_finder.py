# job1_track_finder.py
from datetime import datetime, timezone
import json
import os
import config
import feedparser
import feishu_db
import llm_engine
import notifier
import requests

API_STATUS_FILE = "docs/api_status.json"


def save_api_status(key, ok, msg):
  os.makedirs("docs", exist_ok=True)
  data = {}
  if os.path.exists(API_STATUS_FILE):
    try:
      with open(API_STATUS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    except Exception:
      pass
  data[key] = {"ok": ok, "msg": msg}
  with open(API_STATUS_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)


def get_coingecko_hot_categories():
  url = "https://api.coingecko.com/api/v3/coins/categories"
  headers = {"accept": "application/json", "User-Agent": "Mozilla/5.0"}
  if config.COINGECKO_API_KEY:
    headers["x-cg-demo-api-key"] = config.COINGECKO_API_KEY

  try:
    res = requests.get(url, headers=headers, timeout=20).json()
    if not isinstance(res, list):
      save_api_status("coingecko", False, f"返回格式异常: { str(res)[:50] }")
      return []

    # 剔除稳定币、锚定币、生态大杂烩等不适合选币的伪赛道
    blacklist = [
        "stablecoin",
        "backed",
        "wrapped",
        "bridged",
        "index",
        "ecosystem",
        "peg",
        "portfolio",
        "alleged-sec",
    ]
    valid = []
    for c in res:
      if not isinstance(c, dict):
        continue
      cid = str(c.get("id", "")).lower()
      if any(b in cid for b in blacklist):
        continue
      if (c.get("volume_24h") or 0) > 20000000 and c.get(
          "market_cap_change_24h"
      ) is not None:
        valid.append(c)

    top_cats = sorted(
        valid, key=lambda x: x["market_cap_change_24h"], reverse=True
    )[:10]
    save_api_status(
        "coingecko", True, f"正常 (已过滤稳定币，捕获 {len(top_cats)} 个活跃赛道)"
    )
    return top_cats
  except Exception as e:
    save_api_status("coingecko", False, f"请求失败: {e}")
    return []


def get_vc_funding_news():
  """双通道获取一级市场融资：1. DeFiLlama全球VC融资API(主力) + 2. 媒体快讯RSS"""
  funding_list = []
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
      )
  }

  # 通道1：DeFiLlama 官方免费融资数据库 (全球最新VC融资，100%稳定)
  try:
    res = requests.get(
        "https://api.llama.fi/raises", headers=headers, timeout=20
    ).json()
    raises = res.get("raises", [])
    # 按时间戳倒序，取最新披露的 12 笔融资
    raises.sort(key=lambda x: x.get("date", 0), reverse=True)
    for r in raises[:12]:
      name = r.get("name", "")
      sector = r.get("category") or r.get("sector") or "Web3"
      amount = r.get("amount") or "未披露"
      lead = ", ".join(r.get("leadInvestors", [])) or "知名机构"
      funding_list.append(
          f"[VC融资] 项目:{name} | 赛道:{sector} | 金额:${amount}M |"
          f" 领投:{lead}"
      )
  except Exception as e:
    print(f"DeFiLlama 融资接口跳过: {e}")

  # 通道2：带浏览器伪装头抓取媒体 RSS
  rss_urls = [
      "https://rss.panewslab.com/zh/tvsq/rss",
      "https://cointelegraph.com/rss",
  ]
  for url in rss_urls:
    try:
      resp = requests.get(url, headers=headers, timeout=12)
      feed = feedparser.parse(resp.content)
      for entry in feed.entries[:25]:
        title = entry.get("title", "")
        if any(
            k in title.lower()
            for k in ["融资", "领投", "万美元", "fund", "raise", "million", "invest"]
        ):
          funding_list.append(f"[媒体快讯] {title}")
    except Exception:
      pass

  if funding_list:
    save_api_status("vc_media", True, f"正常 (已捕获 {len(funding_list)} 条最新VC融资情报)")
  else:
    save_api_status("vc_media", False, "未抓取到融资快讯")
  return funding_list[:15]


def run():
  print("📡 开始执行 Job1：全网潜力赛道嗅探...")
  cg_cats = get_coingecko_hot_categories()
  vc_news = get_vc_funding_news()

  if not cg_cats:
    print("未获取到有效赛道数据，本次任务结束。")
    return

  cats_str = "\n".join([
      f"- ID: {c['id']} | 名称: {c['name']} | 24h涨幅:"
      f" {c['market_cap_change_24h']:.2f}%"
      for c in cg_cats
  ])
  news_str = "\n".join(vc_news) if vc_news else "今日暂无重大融资快讯"

  prompt = f"""
【二级市场领涨板块（已剔除稳定币）】：
{cats_str}

【一级市场最新VC融资与媒体情报】：
{news_str}

请结合【一级VC融资热门方向】与【二级市场资金流向】，从上述二级板块列表中挑选出 3 个最具爆发潜力的核心赛道（id 必须严格来自上述二级板块列表的真实 ID）。
如果某个板块同时契合近期VC融资热点，请在 source 中标记为 "🔥一级VC融资+二级共振"，并在 comment 中点明有哪些融资动态或叙事逻辑。
严格输出 JSON 数组格式：
[
    {{"id": "板块真实ID", "name": "板块中文/英文名", "source": "🔥一级VC融资+二级共振 或 二级主力流入", "change_24h": 12.5, "comment": "结合VC融资与二级行情的核心逻辑点评"}}
]
"""
  print("🧠 正在呼叫 AI 大模型提炼核心风口赛道...")
  try:
    raw_reply = llm_engine.ask_ai(prompt, role="default")
    ai_picks = llm_engine.extract_json(raw_reply)
    save_api_status("llm", True, "正常 (GLM / Groq 响应成功)")
  except Exception as e:
    save_api_status("llm", False, f"异常: {str(e)[:60]}")
    print(f"⚠️ AI 赛道提炼异常，使用涨幅榜前两名保底: {e}")
    ai_picks = [
        {
            "id": c["id"],
            "name": c["name"],
            "source": "二级主力流入",
            "change_24h": c["market_cap_change_24h"],
            "comment": "24小时主力资金净流入居前",
        }
        for c in cg_cats[:2]
    ]

  
