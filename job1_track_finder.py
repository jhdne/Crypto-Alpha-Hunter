# job1_track_finder.py
import config
import feedparser
import feishu_db
import llm_engine
import notifier
import requests


def get_coingecko_hot_categories():
  url = "https://api.coingecko.com/api/v3/coins/categories"
  headers = {"accept": "application/json", "User-Agent": "Mozilla/5.0"}
  if config.COINGECKO_API_KEY:
    headers["x-cg-demo-api-key"] = config.COINGECKO_API_KEY

  res = requests.get(url, headers=headers, timeout=20).json()
  if not isinstance(res, list):
    print(f"⚠️ CoinGecko 接口返回异常: {res}")
    return []

  # 修复点：使用 (c.get("volume_24h") or 0) 防止 NoneType 报错
  valid = [
      c
      for c in res
      if isinstance(c, dict)
      and (c.get("volume_24h") or 0) > 50000000
      and c.get("market_cap_change_24h") is not None
  ]
  return sorted(
      valid, key=lambda x: x["market_cap_change_24h"], reverse=True
  )[:8]


def get_vc_funding_news():
  rss_urls = ["https://rss.panewslab.com/zh/tvsq/rss"]
  funding_news = []
  for url in rss_urls:
    try:
      feed = feedparser.parse(url)
      for entry in feed.entries[:30]:
        if any(
            k in entry.title
            for k in ["融资", "领投", "万美元", "百万美元", "参投"]
        ):
          funding_news.append(entry.title)
    except Exception as e:
      print(f"RSS抓取跳过: {e}")
  return funding_news


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
    【二级市场暴涨板块】：\n{cats_str}
    【一级市场最新融资快讯】：\n{news_str}
    请剔除纯粹由单个土狗带动的伪板块，挑选出 2~3 个最具叙事潜力和资金热度的核心赛道（必须从上述二级板块中选择真实存在的 ID）。
    严格输出 JSON 数组格式：
    [
        {{"id": "板块真实ID", "name": "板块名称", "source": "二级暴涨 或 一级+二级共振", "change_24h": 12.5, "comment": "一句话核心逻辑"}}
    ]
    """
  print("🧠 正在呼叫 AI 大模型提炼核心风口赛道...")
  ai_picks = llm_engine.extract_json(llm_engine.ask_ai(prompt, role="default"))

  # 查重并写入飞书表2
  existing_records = feishu_db.get_records(config.TABLE_ID_RADAR)
  existing_ids = {
      r.get("fields", {}).get("赛道ID")
      for r in existing_records
      if "fields" in r
  }

  new_tracks_msg = []
  for pick in ai_picks:
    if pick["id"] not in existing_ids:
      res = feishu_db.add_record(
          config.TABLE_ID_RADAR,
          {
              "赛道ID": str(pick["id"]),
              "赛道名称": str(pick["name"]),
              "发现来源": str(pick.get("source", "二级暴涨")),
              "24h涨幅(%)": round(float(pick.get("change_24h") or 0), 2),
              "AI赛道简评": str(pick.get("comment", "")),
              "人工状态": "允许深挖",
          },
      )
      print(f"✅ 已写入飞书赛道表: {pick['name']} | 状态: {res.get('msg')}")
      new_tracks_msg.append(
          f"- **{pick['name']}** (`{pick['id']}`)：{pick['comment']}"
      )

  if new_tracks_msg:
    notifier.send_wechat(
        "📡 发现新热门赛道并已加入深挖队列", "\n".join(new_tracks_msg)
    )
  else:
    print("今日热门赛道均已在库中，无新增赛道。")


if __name__ == "__main__":
  run()
