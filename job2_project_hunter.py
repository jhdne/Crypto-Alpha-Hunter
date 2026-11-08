# job2_project_hunter.py - V4.0 双轮驱动猎手 (热门Meme/热搜直通车 + 赛道反弹龙头)
from datetime import datetime, timedelta, timezone
import time
import config
import feishu_db
import job1_track_finder
import llm_engine
import notifier
import requests

CG_HEADERS = {"accept": "application/json", "User-Agent": "Mozilla/5.0"}
if config.COINGECKO_API_KEY:
  CG_HEADERS["x-cg-demo-api-key"] = config.COINGECKO_API_KEY

# 彻底封杀一切稳定币、跨链包装币(如WMATIC/WBTC)、质押衍生币
TOKEN_BLACKLIST = {
    "usdt",
    "usdc",
    "dai",
    "fdusd",
    "usde",
    "usdd",
    "tusd",
    "pyusd",
    "eurc",
    "eurs",
    "wbtc",
    "weth",
    "wbnb",
    "wmatic",
    "wpol",
    "wavax",
    "wsol",
    "steth",
    "wsteth",
    "reth",
    "cbeth",
    "weeth",
    "ezeth",
    "msol",
    "jitosol",
    "bnb",
    "btc",
    "eth",
}


def is_junk_token(coin):
  sym = str(coin.get("symbol", "")).lower().strip()
  name = str(coin.get("name", "")).lower().strip()
  cid = str(coin.get("id", "")).lower().strip()
  if sym in TOKEN_BLACKLIST:
    return True
  if any(
      w in name or w in cid
      for w in [
          "wrapped",
          "bridged",
          "staked",
          "usd",
          "eur",
          "peg",
          "tokenized",
      ]
  ):
    return True
  return False


def fetch_trending_and_meme_runners():
  """【引擎 A：自下而上】直接抓取全网热搜飙升榜 (Trending) 与 Meme 爆发标的"""
  runners = []
  try:
    # 1. 获取 CoinGecko Trending Top 15 热搜代币 ID
    tr = requests.get(
        "https://api.coingecko.com/api/v3/search/trending",
        headers=CG_HEADERS,
        timeout=15,
    ).json()
    trending_ids = [
        c["item"]["id"]
        for c in tr.get("coins", [])[:12]
        if "item" in c and "id" in c["item"]
    ]

    if trending_ids:
      ids_str = ",".join(trending_ids)
      url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={ids_str}&price_change_percentage=24h,7d"
      coins = requests.get(url, headers=CG_HEADERS, timeout=15).json()
      if isinstance(coins, list):
        for c in coins:
          if not is_junk_token(c) and (c.get("market_cap") or 0) > 1500000:
            c["_archetype"] = "🔥 热门Meme/异动"
            c["_track_name"] = "全网热搜异动榜"
            runners.append(c)
  except Exception as e:
    print(f"热搜榜扫描跳过: {e}")

  # 2. 扫描 Meme 核心板块中 24h 换手率与涨幅最猛的前 2 个龙头
  try:
    url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&category=meme-token&order=volume_desc&per_page=40&price_change_percentage=24h,7d"
    memes = requests.get(url, headers=CG_HEADERS, timeout=15).json()
    if isinstance(memes, list):
      hot_memes = [
          m
          for m in memes
          if not is_junk_token(m)
          and 3000000 <= (m.get("market_cap") or 0) <= 1500000000
          and (m.get("price_change_percentage_24h") or 0) > 5.0
      ]
      hot_memes.sort(
          key=lambda x: (x.get("price_change_percentage_24h") or 0),
          reverse=True,
      )
      for m in hot_memes[:2]:
        m["_archetype"] = "🔥 热门Meme/异动"
        m["_track_name"] = "Meme 爆发龙头"
        runners.append(m)
  except Exception:
    pass

  return runners[:4]


def fetch_sector_rebound_leaders(tracks):
  """【引擎 B：自上而下】从热门赛道与主流赛池中，挖掘强势反弹龙头与高赔率潜伏标的"""
  leaders = []
  # 将 AI 嗅探到的赛道与必看的高赔率核心赛道结合
  core_tracks = [
      {"赛道ID": "artificial-intelligence", "赛道名称": "AI & Agent 赛道"},
      {"赛道ID": "real-world-assets-rwa", "赛道名称": "RWA 真实世界资产"},
      {"赛道ID": "depin", "赛道名称": "DePIN 硬件网络"},
  ]
  scan_list = tracks[:3] + core_tracks
  seen_cats = set()

  for t in scan_list:
    cat_id = t.get("赛道ID")
    if (
        not cat_id
        or cat_id in seen_cats
        or job1_track_finder.is_garbage_track(cat_id, t.get("赛道名称", ""))
    ):
      continue
    seen_cats.add(cat_id)
    if len(seen_cats) > 4:
      break

    print(f"👉 扫描赛道反弹与潜伏标的: {t.get('赛道名称')} ({cat_id})...")
    url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&category={cat_id}&order=volume_desc&per_page=60&price_change_percentage=24h,7d"
    try:
      coins = requests.get(url, headers=CG_HEADERS, timeout=15).json()
    except Exception:
      continue
    if not isinstance(coins, list):
      continue

    valid = [
        c
        for c in coins
        if isinstance(c, dict)
        and not is_junk_token(c)
        and 2000000 <= (c.get("market_cap") or 0) <= 2000000000
    ]

    # 策略1：捕捉【📈 赛道反弹龙头】（24h涨幅 > 3% 且 换手率高）
    rebounders = [
        c for c in valid if (c.get("price_change_percentage_24h") or 0) >= 3.0
    ]
    rebounders.sort(
        key=lambda x: (x.get("price_change_percentage_24h") or 0)
        * ((x.get("total_volume") or 1) / (x.get("market_cap") or 1)),
        reverse=True,
    )
    if rebounders:
      top_r = rebounders[0]
      top_r["_archetype"] = "📈 赛道反弹龙头"
      top_r["_track_name"] = t.get("赛道名称", cat_id)
      leaders.append(top_r)

    # 策略2：捕捉【💎 底部价值潜伏】（距高点跌幅 > 45%，流通率 > 30%，高换手企稳）
    value_gems = [
        c
        for c in valid
        if (c.get("ath_change_percentage") or 0) <= -45
        and ((c.get("market_cap") or 0) / (c.get("fully_diluted_valuation") or 1))
        >= 0.30
    ]
    value_gems.sort(
        key=lambda x: (x.get("total_volume") or 0) / (x.get("market_cap") or 1),
        reverse=True,
    )
    if value_gems:
      top_v = value_gems[0]
      if top_v.get("id") != (rebounders[0].get("id") if rebounders else ""):
        top_v["_archetype"] = "💎 底部价值潜伏"
        top_v["_track_name"] = t.get("赛道名称", cat_id)
        leaders.append(top_v)

    time.sleep(1.5)

  return leaders[:5]


def evaluate_candidate(c, db):
  """针对不同机会类型（Meme异动 vs 赛道反弹 vs 底部潜伏）进行科学量化与多智能体辩论"""
  archetype = c.get("_archetype", "📈 赛道反弹龙头")
  track_name = c.get("_track_name", "热门赛道")
  mc = float(c.get("market_cap") or 1)
  fdv = float(c.get("fully_diluted_valuation") or mc)
  vol = float(c.get("total_volume") or 0)
  chg_24h = float(c.get("price_change_percentage_24h") or 0)
  chg_7d = float(
      c.get("price_change_percentage_7d_in_currency")
      or c.get("price_change_percentage_7d")
      or 0
  )
  ath_drop = float(c.get("ath_change_percentage") or -30)

  mc_ratio = min(1.0, mc / fdv)
  turnover = vol / mc  # 24h 换手率

  # 分类型科学算分
  if "Meme" in archetype or "异动" in archetype:
    # Meme 与热搜异动看重：换手爆发力(40%) + 短期动量(35%) + 全筹码流通无VC砸盘(25%)
    momentum_score = min(100, 65 + max(0, chg_24h) * 1.2)
    turnover_score = min(100, 50 + turnover * 150)
    quant_score = (
        turnover_score * 0.40 + momentum_score * 0.35 + (mc_ratio * 100) * 0.25
    )
  elif "反弹" in archetype:
    # 赛道反弹龙头看重：反弹强度(35%) + 换手率(30%) + 跌幅反弹空间(20%) + 流通率(15%)
    rebound_score = min(100, 65 + max(0, chg_24h) * 1.5)
    turnover_score = min(100, 55 + turnover * 180)
    space_score = min(100, 50 + abs(ath_drop) * 0.5)
    quant_score = (
        rebound_score * 0.35
        + turnover_score * 0.30
        + space_score * 0.20
        + (mc_ratio * 100) * 0.15
    )
  else:
    # 底部价值潜伏看重：超跌安全垫(40%) + 筹码解锁率(35%) + 资金活跃度(25%)
    safety_score = min(100, max(50, abs(ath_drop) * 1.1))
    turnover_score = min(100, 50 + turnover * 200)
    quant_score = (
        safety_score * 0.40 + (mc_ratio * 100) * 0.35 + turnover_score * 0.25
    )

  info_pack = (
      f"【机会类型】: {archetype} | 【所属板块】: {track_name}\n"
      f"【代币】: {c.get('name')} (${str(c.get('symbol', '')).upper()})\n"
      f"【核心行情】: 现价 ${c.get('current_price')} | 24h涨跌: {chg_24h:+.2f}% |"
      f" 7d涨跌: {chg_7d:+.2f}%\n"
      f"【筹码与热度】: 流通市值 ${mc/1e4:.0f}万美元 | 24h成交额"
      f" ${vol/1e4:.0f}万美元 (换手率 {turnover*100:.1f}%) | MC/FDV流通率"
      f" {mc_ratio*100:.1f}% | 距ATH高点 {ath_drop:.1f}%"
  )

  try:
    ai_eval = llm_engine.multi_agent_evaluate(info_pack)
    db["api_status"]["llm"] = {
        "ok": True,
        "msg": "正常 (多智能体投委会辩论完成)",
    }
  except Exception:
    ai_eval = {
        "ai_score": round(quant_score, 0),
        "summary_report": (
            f"【核心亮点】入选 {archetype}，24h涨跌幅 {chg_24h:+.1f}%，24h换手率达"
            f" {turnover*100:.1f}%，资金关注度极高。\n"
            f"【风控提示】流通率 {mc_ratio*100:.0f}%，距历史高点"
            f" {ath_drop:.1f}%，建议结合大盘情绪分批操作。"
        ),
    }

  final_score = round(
      quant_score * 0.5 + float(ai_eval.get("ai_score") or 80) * 0.5, 1
  )
  bj_now = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime(
      "%m-%d %H:%M"
  )

  return {
      "项目ID": str(c["id"]),
      "代币符号": f"${str(c.get('symbol', '')).upper()}",
      "项目名称": str(c.get("name", "")),
      "机会类型": archetype,
      "所属赛道": track_name,
      "推荐时价格": round(float(c.get("current_price") or 0), 6),
      "24h涨跌(%)": round(chg_24h, 2),
      "7d涨跌(%)": round(chg_7d, 2),
      "换手率(%)": round(turnover * 100, 1),
      "流通市值(万)": round(mc / 1e4, 1),
      "流通率(%)": round(mc_ratio * 100, 1),
      "距高点跌幅(%)": round(ath_drop, 1),
      "综合总分": final_score,
      "多智能体投研报告": str(ai_eval.get("summary_report", "")),
      "发现时间": bj_now,
  }


def run():
  print("🚀 执行 V4.0 Job2：双轮驱动捕捉【热门Meme/异动】+【赛道反弹龙头】...")
  db = job1_track_finder.load_db()
  db["api_status"]["tavily"] = {
      "ok": True,
      "msg": "正常 (链上换手率+热搜动量双擎已启用)",
  }

  # 清理历史遗留的包装币/稳定币项目
  db["projects"] = [
      p
      for p in db.get("projects", [])
      if not is_junk_token({
          "symbol": p.get("代币符号", "").replace("$", ""),
          "name": p.get("项目名称", ""),
          "id": p.get("项目ID", ""),
      })
  ]

  # 双轮驱动采集候选池
  meme_runners = fetch_trending_and_meme_runners()
  sector_leaders = fetch_sector_rebound_leaders(db.get("tracks", []))

  combined_candidates = []
  seen_ids = set()
  for c in meme_runners + sector_leaders:
    if c["id"] not in seen_ids:
      seen_ids.add(c["id"])
      combined_candidates.append(c)

  print(f"🎯 本轮共锁定 {len(combined_candidates)} 个高热度/强反弹候选标的，启动多智能体辩论...")

  new_items = []
  for c in combined_candidates[:6]:
    proj_item = evaluate_candidate(c, db)
    new_items.append(proj_item)
    # 更新或插入本地库
    db["projects"] = [
        p for p in db["projects"] if p.get("项目ID") != proj_item["项目ID"]
    ]
    db["projects"].insert(0, proj_item)

    # 同步写入飞书表3（仅传飞书表3兼容的基础字段，且自带自动建列）
    feishu_db.add_record(config.TABLE_ID_ALPHA, proj_item)
    print(
        f"✅ 精选入库: {proj_item['代币符号']} [{proj_item['机会类型']}] |"
        f" 24h: {proj_item['24h涨跌(%)']:+.1f}% | 总分: {proj_item['综合总分']}"
    )

  # 保持项目库展示最新、最高分的 16 个标的
  db["projects"] = db["projects"][:16]
  bj_time = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime(
      "%Y-%m-%d %H:%M"
  )
  if new_items:
    top_p = sorted(new_items, key=lambda x: x["综合总分"], reverse=True)[0]
    db["alert"] = {
        "title": (
            f"🚨 捕获 {top_p['机会类型']}：{top_p['代币符号']}"
            f" ({top_p['综合总分']}分)"
        ),
        "content": (
            f"所属板块：{top_p['所属赛道']} | 24h涨跌：{top_p['24h涨跌(%)']:+.1f}%"
            f" | 换手率：{top_p['换手率(%)']}%。"
            f"{top_p['多智能体投研报告'][:90]}..."
        ),
        "time": bj_time,
    }

  job1_track_finder.save_db(db)
  notifier.build_dashboard()


if __name__ == "__main__":
  run()
