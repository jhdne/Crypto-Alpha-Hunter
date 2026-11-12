# job3_self_evolver.py - V6.0 每4小时高频实盘回测与动态风控基因进化引擎
import copy
from datetime import datetime, timezone, timedelta
import requests
import config
import feishu_db
import llm_engine
import notifier


def _safe_float(val, default=0.0):
    if val is None or val == "":
        return default
    if isinstance(val, list):
        val = val[0].get("text", "") if (val and isinstance(val[0], dict)) else (val[0] if val else "")
    try:
        return float(str(val).replace("$", "").replace("%", "").replace(",", "").strip())
    except Exception:
        return default


def _safe_str(val, default=""):
    if val is None:
        return default
    if isinstance(val, list):
        return ", ".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in val)
    return str(val).strip()


def _fetch_current_price(coin_id, symbol="", contract_address=""):
    headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    if config.COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = config.COINGECKO_API_KEY

    # 1. 优先通过合约地址在 DexScreener 查询链上实时价格（最快、最准）
    if contract_address:
        try:
            d_res = requests.get(
                f"https://api.dexscreener.com/latest/dex/tokens/{contract_address}",
                timeout=10,
            ).json()
            pairs = d_res.get("pairs") or []
            if pairs:
                best_p = max(
                    pairs,
                    key=lambda x: float((x.get("liquidity") or {}).get("usd") or 0),
                )
                p_usd = best_p.get("priceUsd")
                if p_usd:
                    return float(p_usd)
        except Exception:
            pass

    # 2. 通过 CoinGecko ID 查询
    if coin_id and not str(coin_id).startswith("dex_"):
        try:
            res = requests.get(
                f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd",
                headers=headers,
                timeout=12,
            ).json()
            price = res.get(coin_id, {}).get("usd")
            if price:
                return float(price)
        except Exception:
            pass

    # 3. 通过代币符号在 DexScreener 搜索主池价格
    if symbol:
        try:
            d_res = requests.get(
                f"https://api.dexscreener.com/latest/dex/search?q={symbol}",
                timeout=10,
            ).json()
            pairs = [
                p for p in (d_res.get("pairs") or [])
                if ((p.get("baseToken") or {}).get("symbol") or "").upper() == symbol.upper()
            ]
            if pairs:
                best_p = max(
                    pairs,
                    key=lambda x: float((x.get("liquidity") or {}).get("usd") or 0),
                )
                p_usd = best_p.get("priceUsd")
                if p_usd:
                    return float(p_usd)
        except Exception:
            pass
    return None


def _clamp(val, low, high):
    return round(max(low, min(high, float(val))), 2)


def run():
    print("🧬 [Job3 V6.0] 启动高频实盘盈亏回测 + 买点与市值闸门自我进化...")
    local_data = notifier.load_local_db()
    evo_state = local_data.get("evolution_state") or copy.deepcopy(config.DEFAULT_EVOLUTION_STATE)
    projects = local_data.get("projects", [])

    performance_summary = []
    rois = []
    wins = 0
    best_pick = ("暂无", -999.0)
    worst_pick = ("暂无", 999.0)

    # 1. 回测本地数据库中的最新推荐项目，并实时更新其最新价格与浮盈 (live_roi_pct)
    for p in projects:
        sym = _safe_str(p.get("symbol")).upper()
        cid = _safe_str(p.get("coingecko_id") or p.get("id"))
        c_addr = _safe_str(p.get("contract_address"))
        entry_price = _safe_float(p.get("price"), 0.0)
        if entry_price <= 0 or not sym:
            continue

        live_price = _fetch_current_price(cid, sym, c_addr)
        if live_price and live_price > 0:
            roi = round((live_price - entry_price) / entry_price * 100, 2)
            p["live_price"] = live_price
            p["live_roi_pct"] = roi
            rois.append(roi)
            if roi >= 5.0:
                wins += 1
            if roi > best_pick[1]:
                best_pick = (f"${sym} ({roi:+.1f}%)", roi)
            if roi < worst_pick[1]:
                worst_pick = (f"${sym} ({roi:+.1f}%)", roi)

            entry_chg24 = _safe_float(p.get("change_24h"), 0.0)
            entry_mc = _safe_float(p.get("market_cap"), 0.0)
            entry_buy_ratio = _safe_float(p.get("buy_ratio"), 50.0)
            outcome_tag = "🏆盈利金狗" if roi >= 10 else ("🩸追高回撤/亏损" if roi <= -6 else "⏳震荡蓄势")

            performance_summary.append(
                f"- [{outcome_tag}] ${sym} ({p.get('opp_type', '')}): 推荐后真实收益 {roi:+.2f}% | "
                f"当时入选24h涨幅: {entry_chg24:+.1f}% | 当时流通市值: ${entry_mc:.1f}万 | "
                f"当时链上买盘占比: {entry_buy_ratio:.1f}% | 当时建仓窗口: {p.get('entry_timing', '早期')}"
            )

    # 2. 同步回测并更新飞书表3中的历史记录（如果配置了飞书）
    alpha_records = feishu_db.get_records(config.TABLE_ID_ALPHA)
    for r in alpha_records[:15]:
        fields = r.get("fields", {})
        coin_id = _safe_str(fields.get("项目ID"))
        symbol = _safe_str(fields.get("代币符号"))
        contract_addr = _safe_str(fields.get("合约地址"))
        old_price = _safe_float(fields.get("推荐时价格"), 0.0)
        if old_price <= 0 or (not coin_id and not symbol):
            continue
        new_price = _fetch_current_price(coin_id, symbol, contract_addr)
        if new_price and new_price > 0:
            roi = round((new_price - old_price) / old_price * 100, 2)
            feishu_db.update_record(
                config.TABLE_ID_ALPHA,
                r["record_id"],
                {"7日后价格": new_price, "7日真实涨幅(%)": roi},
            )
            if len(performance_summary) < 12:
                performance_summary.append(
                    f"- ${symbol}: 推荐后真实涨跌幅 {roi:+.2f}% | 当时24h涨幅: {_safe_str(fields.get('24h涨幅(%)'))}% "
                    f"| 当时流通市值: ${_safe_str(fields.get('流通市值(万)'))}万"
                )

    tz_bj = timezone(timedelta(hours=8))
    now_str = datetime.now(tz_bj).strftime("%Y-%m-%d %H:%M")

    if not performance_summary:
        print("ℹ️ 尚无历史持仓样本可回测，初始化 V6.0 极早期狙击基因参数。")
        local_data["evolution_state"] = evo_state
        notifier.save_local_db(local_data)
        return

    total_tested = len(rois) if rois else len(performance_summary)
    win_rate = round((wins / len(rois)) * 100, 1) if rois else 50.0
    avg_roi = round(sum(rois) / len(rois), 2) if rois else 0.0

    curr_guardrails = evo_state.get("guardrails") or config.DEFAULT_EVOLUTION_STATE["guardrails"]
    curr_weights = evo_state.get("weights") or config.DEFAULT_EVOLUTION_STATE["weights"]

    prompt = f"""
你是加密量化基金的首席进化架构师 (Self-Evolver Agent)。
用户的核心诉求是：【拒绝错过发币早期最佳窗口、拒绝在24h涨幅过高时高位接盘、拒绝大市值低赔率项目，要在最早期、最安全的位置捕获最具爆发力的项目！】

以下是本系统近期推荐项目的【真实市场表现回测归因】：
- 回测样本数：{total_tested} 个 | 当前正收益胜率：{win_rate}% | 平均收益率：{avg_roi:+.2f}%
- 最佳捕获：{best_pick[0]} | 最大回撤教训：{worst_pick[0]}
明细数据：
{chr(10).join(performance_summary)}

当前系统正在使用的动态风控闸门 (guardrails)：
{curr_guardrails}
当前系统正在使用的五维评分权重 (weights)：
{curr_weights}

请深度剖析上述【🩸追高回撤/亏损】与【🏆盈利金狗】的共同规律（重点检查亏损项目是否因为入选时24h涨幅过高、市值偏大或买盘占比不足），并立即进化下一轮猎杀参数：
1. 动态调整 `guardrails`（严格限制在以下安全边界内）：
   - `max_meme_mc_wan`: Meme最大市值上限(万USD)，范围 400 ~ 2000（若近期大市值滞涨，请果断下调至 600~1200）
   - `max_narrative_mc_wan`: 叙事黑马最大市值上限(万USD)，范围 1500 ~ 6000（若大市值表现差，请下调至 2500~4500）
   - `max_24h_pump_limit`: 24h最大防追高涨幅红线(%)，范围 35 ~ 80（若近期因追高亏损，请果断收紧至 40~58！）
   - `sweet_spot_24h_max`: 最佳启动涨幅甜蜜区上限(%)，范围 18 ~ 42
   - `min_buy_ratio_pct`: 最低链上买盘占比(%)，范围 52.0 ~ 58.0
   - `min_score_threshold`: 入选最低综合总分，范围 66.0 ~ 75.0
2. 微调 5 项评分权重（之和必须为 1.00）。
3. 提炼 3 条一针见血的 `tactical_rules`（下一轮直接注入 CIO 脑中的强制狙击与一票否决铁律）。

严格输出纯 JSON 格式：
{{
  "guardrails": {{
    "max_meme_mc_wan": 1000.0,
    "max_narrative_mc_wan": 4000.0,
    "max_24h_pump_limit": 52.0,
    "sweet_spot_24h_max": 30.0,
    "min_buy_ratio_pct": 54.5,
    "min_score_threshold": 69.0
  }},
  "weights": {{
    "early_timing": 0.32,
    "buy_pressure": 0.26,
    "mc_odds": 0.22,
    "track_heat": 0.12,
    "fundamentals": 0.08
  }},
  "evolution_reason": "用90字以内一针见血总结本轮实盘盈亏原因及参数收紧逻辑",
  "tactical_rules": [
    "铁律1：...",
    "铁律2：...",
    "铁律3：..."
  ]
}}
"""
    raw_resp = llm_engine.ask_ai(prompt, role="evolver_agent", temperature=0.25, json_mode=True)
    parsed = llm_engine.extract_json(raw_resp)

    if isinstance(parsed, dict) and isinstance(parsed.get("guardrails"), dict):
        g = parsed["guardrails"]
        new_guardrails = {
            "max_meme_mc_wan": _clamp(g.get("max_meme_mc_wan", 1200), 400, 2000),
            "max_narrative_mc_wan": _clamp(g.get("max_narrative_mc_wan", 4000), 1500, 6000),
            "max_24h_pump_limit": _clamp(g.get("max_24h_pump_limit", 58), 35, 80),
            "sweet_spot_24h_max": _clamp(g.get("sweet_spot_24h_max", 32), 18, 42),
            "min_buy_ratio_pct": _clamp(g.get("min_buy_ratio_pct", 54.0), 52.0, 58.0),
            "min_score_threshold": _clamp(g.get("min_score_threshold", 68.5), 66.0, 75.0),
        }
        evo_state["guardrails"] = new_guardrails

        if isinstance(parsed.get("weights"), dict):
            w = parsed["weights"]
            w_sum = sum(float(w.get(k, 0.2)) for k in ["early_timing", "buy_pressure", "mc_odds", "track_heat", "fundamentals"])
            if w_sum > 0:
                evo_state["weights"] = {
                    k: round(float(w.get(k, 0.2)) / w_sum, 3)
                    for k in ["early_timing", "buy_pressure", "mc_odds", "track_heat", "fundamentals"]
                }

        if parsed.get("evolution_reason"):
            evo_state["evolution_reason"] = str(parsed["evolution_reason"]).strip()
        if isinstance(parsed.get("tactical_rules"), list) and parsed["tactical_rules"]:
            evo_state["tactical_rules"] = [str(r) for r in parsed["tactical_rules"][:4]]

    evo_state["generation"] = int(evo_state.get("generation", 1)) + 1
    evo_state["last_evolved_at"] = now_str
    evo_state["win_rate_pct"] = win_rate
    evo_state["avg_roi_pct"] = avg_roi
    evo_state["total_tested"] = total_tested
    evo_state["best_pick"] = best_pick[0]
    evo_state["worst_pick"] = worst_pick[0]

    # 同步最新权重到飞书表1（如果配置了飞书）
    cfg_records = feishu_db.get_records(config.TABLE_ID_CONFIG)
    if cfg_records:
        w_Now = evo_state["weights"]
        feishu_w = {
            "价格安全权重": round(w_Now.get("early_timing", 0.30) * 100),
            "营销背书权重": round(w_Now.get("buy_pressure", 0.25) * 100),
            "市值赔率权重": round(w_Now.get("mc_odds", 0.20) * 100),
            "赛道热度权重": round(w_Now.get("track_heat", 0.15) * 100),
            "技术实力权重": round(w_Now.get("fundamentals", 0.10) * 100),
        }
        feishu_db.update_record(config.TABLE_ID_CONFIG, cfg_records[0]["record_id"], feishu_w)

    local_data["projects"] = projects
    local_data["evolution_state"] = evo_state
    notifier.save_local_db(local_data)
    print(
        f"✅ [自我进化完成 -> Gen #{evo_state['generation']}] "
        f"胜率: {win_rate}% | 均益: {avg_roi:+.2f}% | "
        f"最新防追高红线: +{evo_state['guardrails']['max_24h_pump_limit']}% | "
        f"Meme市值上限: ${evo_state['guardrails']['max_meme_mc_wan']}万"
    )


if __name__ == "__main__":
    run()
