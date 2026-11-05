# job2_project_hunter.py
from datetime import datetime
import time
import config
import feishu_db
import llm_engine
import notifier
import requests

CG_HEADERS = (
    {"x-cg-demo-api-key": config.COINGECKO_API_KEY}
    if config.COINGECKO_API_KEY
    else {}
)


def search_vc_and_buzz(coin_name, symbol):
  """使用 Tavily 免费搜索项目的 VC 投资背景与市场热度"""
  if not config.TAVILY_API_KEY:
    return "未配置Tavily，无外部VC搜索数据", 50
  try:
    res = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": config.TAVILY_API_KEY,
            "query": f"{coin_name} {symbol} crypto funding investors VC",
            "max_results": 3,
        },
        timeout=15,
    ).json()
    text = " ".join([r.get("content", "") for r in res.get("results", [])])
    top_vcs = [
        "Binance",
        "a16z",
        "Paradigm",
        "Polychain",
        "Coinbase",
        "Pantera",
        "Multicoin",
        "Animoca",
        "Sequoia",
        "Dragonfly",
    ]
    hit_vcs = [vc for vc in top_vcs if vc.lower() in text.lower()]
    score = min(100, 50 + len(hit_vcs) * 20)
    return (
        f"命中顶级VC: {hit_vcs if hit_vcs else '未查到知名VC'} | 摘要:"
        f" {text[:300]}",
        score,
    )
  except Exception:
    return "搜索超时", 50


def run():
  print("🔍 开始执行 Job2：项目漏斗筛选与多智能体评估...")
  # 1. 读取飞书表1的权重配置
  cfg_records = feishu_db.get_records(config.TABLE_ID_CONFIG)
  w = cfg_records[0]["fields"] if cfg_records else {}
  min_mc = float(w.get("最低市值(万美元)", 500)) * 10000
  max_mc = float(w.get("最高市值(万美元)", 15000)) * 10000

  # 2. 读取飞书表2中“允许深挖”的赛道和表3已存在的项目
  radar_records = feishu_db.get_records(config.TABLE_ID_RADAR)
  approved_tracks = [
      r["fields"]
      for r in radar_records
      if r.get("fields", {}).get("人工状态") == "允许深挖"
  ]

  alpha_records = feishu_db.get_records(config.TABLE_ID_ALPHA)
  existing_coins = {
      r["fields"].get("项目ID") for r in alpha_records if "fields" in r
  }

  for track in approved_tracks[:3]:  # 每次最多扫3个赛道防API超限
    cat_id = track.get("赛道ID")
    print(f"正在扫描赛道: {cat_id}...")
    url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&category={cat_id}&per_page=100"
    coins = requests.get(url, headers=CG_HEADERS, timeout=20).json()
    if not isinstance(coins, list):
      continue

    # === 第一层漏斗：硬性规则初筛（0算力消耗） ===
    candidates = []
    for c in coins:
      if c["id"] in existing_coins:
        continue
      mc = c.get("market_cap") or 0
      fdv = c.get("fully_diluted_valuation") or mc
      vol = c.get("total_volume") or 0
      ath_drop = c.get("ath_change_percentage") or 0

      if not (min_mc <= mc <= max_mc):
        continue  # 市值不符
      if vol / mc < 0.04:
        continue  # 换手率低于4%（死水）
      if (mc / fdv) < 0.20:
        continue  # 流通率低于20%（VC天量解锁抛压）
      if ath_drop > -45:
        continue  # 距高点跌幅不足45%（位置太高不安全）
      candidates.append(c)

    # 每个赛道取换手率最高的前 2 个幸存者进入深度背调
    candidates = sorted(
        candidates,
        key=lambda x: x["total_volume"] / x["market_cap"],
        reverse=True,
    )[:2]

    for c in candidates:
      time.sleep(4)  # 礼貌延时，防 CoinGecko 429 限流
      detail = requests.get(
          f"https://api.coingecko.com/api/v3/coins/{c['id']}?localization=false&tickers=false&developer_data=true",
          headers=CG_HEADERS,
          timeout=20,
      ).json()

      # === 第二层漏斗：多维度量化算分 ===
      ath_drop = abs(c.get("ath_change_percentage", -50))
      safety_score = min(100, max(40, (ath_drop - 30) * 1.2))  # 跌得越透越安全

      commits = detail.get("developer_data", {}).get("commit_count_4_weeks", 0)
      tech_score = min(100, 40 + commits * 1.5)  # GitHub代码活跃度

      vc_info, mkt_score = search_vc_and_buzz(c["name"], c["symbol"])
      mc_ratio = c["market_cap"] / (
          c.get("fully_diluted_valuation") or c["market_cap"]
      )
      mc_score = min(100, mc_ratio * 100)

      quant_score = (
          80 * float(w.get("赛道热度权重", 20))
          + safety_score * float(w.get("价格安全权重", 30))
          + tech_score * float(w.get("技术实力权重", 15))
          + mkt_score * float(w.get("营销背书权重", 20))
          + mc_score * float(w.get("市值赔率权重", 15))
      ) / 100.0

      # === 第三层漏斗：多智能体投委会辩论 ===
      desc = detail.get("description", {}).get("en", "")[:500]
      info_pack = (
          f"名称: {c['name']} (${c['symbol'].upper()}) | 赛道:"
          f" {track.get('赛道名称')}\n"
          f"流通市值: ${c['market_cap']/1e4:.0f}万 | 流通率:"
          f" {mc_ratio*100:.1f}% | 距ATH高点跌幅:"
          f" {c['ath_change_percentage']:.1f}%\n"
          f"近4周GitHub代码提交: {commits}次 | 融资与背调: {vc_info}\n"
          f"项目简介: {desc}"
      )
      ai_eval = llm_engine.multi_agent_evaluate(info_pack)
      final_score = round(quant_score * 0.5 + ai_eval["ai_score"] * 0.5, 1)

      # 写入飞书表3
      feishu_db.add_record(
          config.TABLE_ID_ALPHA,
          {
              "项目ID": c["id"],
              "代币符号": f"${c['symbol'].upper()}",
              "所属赛道": track.get("赛道名称"),
              "推荐时价格": c["current_price"],
              "流通市值(万)": round(c["market_cap"] / 1e4, 1),
              "流通率(%)": round(mc_ratio * 100, 1),
              "距高点跌幅(%)": round(c["ath_change_percentage"], 1),
              "综合总分": final_score,
              "多智能体投研报告": ai_eval["summary_report"],
              "发现时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
          },
      )

      # 达到75分以上，触发微信报警！
      if final_score >= 75:
        msg = (
            f"**标的：** ${c['symbol'].upper()} ({c['name']})\n"
            f"**综合得分：** `{final_score}` 分 | **所属风口：**"
            f" {track.get('赛道名称')}\n"
            f"**市值与安全垫：** 市值 ${c['market_cap']/1e4:.0f}万 (流通率"
            f" {mc_ratio*100:.0f}%)，距高点已洗盘"
            f" `{c['ath_change_percentage']:.1f}%`\n"
            f"**多智能体裁决：**\n{ai_eval['summary_report']}"
        )
        notifier.send_wechat(
            f"🚨 发现高潜安全标的 ${c['symbol'].upper()} ({final_score}分)",
            msg,
        )


if __name__ == "__main__":
  run()