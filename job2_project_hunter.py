# job2_project_hunter.py
from datetime import datetime
import time
import config
import feishu_db
import llm_engine
import notifier
import requests

CG_HEADERS = {"accept": "application/json", "User-Agent": "Mozilla/5.0"}
if config.COINGECKO_API_KEY:
  CG_HEADERS["x-cg-demo-api-key"] = config.COINGECKO_API_KEY


def search_vc_and_buzz(coin_name, symbol):
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
  cfg_records = feishu_db.get_records(config.TABLE_ID_CONFIG)
  w = cfg_records[0].get("fields", {}) if cfg_records else {}
  min_mc = float(w.get("最低市值(万美元)") or 50) * 10000
  max_mc = float(w.get("最高市值(万美元)") or 1500) * 10000

  radar_records = feishu_db.get_records(config.TABLE_ID_RADAR)
  approved_tracks = [
      r["fields"]
      for r in radar_records
      if r.get("fields", {}).get("人工状态") == "允许深挖"
  ]

  alpha_records = feishu_db.get_records(config.TABLE_ID_ALPHA)
  existing_coins = {
      r.get("fields", {}).get("项目ID") for r in alpha_records if "fields" in r
  }

  for track in approved_tracks[:3]:
    cat_id = track.get("赛道ID")
    if not cat_id:
      continue
    print(f"正在扫描赛道: {cat_id}...")
    url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&category={cat_id}&per_page=100"
    coins = requests.get(url, headers=CG_HEADERS, timeout=20).json()
    if not isinstance(coins, list):
      continue

    candidates = []
    for c in coins:
      if not isinstance(c, dict) or c.get("id") in existing_coins:
        continue
      mc = float(c.get("market_cap") or 0)
      fdv = float(c.get("fully_diluted_valuation") or mc)
      vol = float(c.get("total_volume") or 0)
      ath_drop = float(c.get("ath_change_percentage") or 0)

      if mc <= 0 or fdv <= 0:
        continue
      if not (min_mc <= mc <= max_mc):
        continue
      if vol / mc < 0.04:
        continue
      if (mc / fdv) < 0.20:
        continue
      if ath_drop > -45:
        continue
      candidates.append(c)

    candidates = sorted(
        candidates,
        key=lambda x: (x.get("total_volume") or 0) / (x.get("market_cap") or 1),
        reverse=True,
    )[:2]

    for c in candidates:
      time.sleep(4)
      detail = requests.get(
          f"https://api.coingecko.com/api/v3/coins/{c['id']}?localization=false&tickers=false&developer_data=true",
          headers=CG_HEADERS,
          timeout=20,
      ).json()
      if not isinstance(detail, dict):
        continue

      ath_drop = abs(float(c.get("ath_change_percentage") or -50))
      safety_score = min(100, max(40, (ath_drop - 30) * 1.2))

      dev_data = detail.get("developer_data") or {}
      commits = int(dev_data.get("commit_count_4_weeks") or 0)
      tech_score = min(100, 40 + commits * 1.5)

      vc_info, mkt_score = search_vc_and_buzz(
          c.get("name", ""), c.get("symbol", "")
      )
      mc_val = float(c.get("market_cap") or 1)
      fdv_val = float(c.get("fully_diluted_valuation") or mc_val)
      mc_ratio = mc_val / fdv_val
      mc_score = min(100, mc_ratio * 100)

      quant_score = (
          80 * float(w.get("赛道热度权重") or 20)
          + safety_score * float(w.get("价格安全权重") or 30)
          + tech_score * float(w.get("技术实力权重") or 15)
          + mkt_score * float(w.get("营销背书权重") or 20)
          + mc_score * float(w.get("市值赔率权重") or 15)
      ) / 100.0

      desc_dict = detail.get("description") or {}
      desc = str(desc_dict.get("en") or "")[:500]
      info_pack = (
          f"名称: {c.get('name')} (${str(c.get('symbol', '')).upper()}) | 赛道:"
          f" {track.get('赛道名称')}\n"
          f"流通市值: ${mc_val/1e4:.0f}万 | 流通率: {mc_ratio*100:.1f}% |"
          f" 距ATH高点跌幅: {c.get('ath_change_percentage') or 0:.1f}%\n"
          f"近4周GitHub代码提交: {commits}次 | 融资与背调: {vc_info}\n"
          f"项目简介: {desc}"
      )
      ai_eval = llm_engine.multi_agent_evaluate(info_pack)
      final_score = round(
          quant_score * 0.5 + float(ai_eval.get("ai_score") or 70) * 0.5, 1
      )

      feishu_db.add_record(
          config.TABLE_ID_ALPHA,
          {
              "项目ID": str(c["id"]),
              "代币符号": f"${str(c.get('symbol', '')).upper()}",
              "所属赛道": str(track.get("赛道名称", "")),
              "推荐时价格": float(c.get("current_price") or 0),
              "流通市值(万)": round(mc_val / 1e4, 1),
              "流通率(%)": round(mc_ratio * 100, 1),
              "距高点跌幅(%)": round(
                  float(c.get("ath_change_percentage") or 0), 1
              ),
              "综合总分": final_score,
              "多智能体投研报告": str(ai_eval.get("summary_report", "")),
              "发现时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
          },
      )

      if final_score >= 75:
        notifier.send_wechat(
            f"🚨 发现高潜安全标的 ${str(c.get('symbol', '')).upper()}"
            f" ({final_score}分)",
            str(ai_eval.get("summary_report", "")),
        )


if __name__ == "__main__":
  run()
