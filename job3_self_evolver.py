# job3_self_evolver.py - V7.0 类脑级策略归因与胜率/盈亏比自主进化引擎
from concurrent.futures import ThreadPoolExecutor
import copy
from datetime import datetime, timezone, timedelta
import requests
import config
import feishu_db
import llm_engine
import notifier
from logger import get_logger
from models import normalize_project

log = get_logger("job3_self_evolver")
_SESSION = requests.Session()


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


def _batch_fetch_dexscreener_prices(contracts: list) -> dict:
    price_map = {}
    clean_addrs = [c.strip() for c in contracts if c and c.strip()]
    if not clean_addrs:
        return price_map

    for i in range(0, len(clean_addrs), 30):
        chunk = ",".join(clean_addrs[i : i + 30])
        try:
            resp = _SESSION.get(
                f"https://api.dexscreener.com/latest/dex/tokens/{chunk}",
                timeout=12,
            )
            if resp.status_code != 200:
                continue
            pairs = resp.json().get("pairs") or []
            best_by_addr = {}
            for p in pairs:
                addr = str((p.get("baseToken") or {}).get("address") or "").lower()
                p_usd = p.get("priceUsd")
                liq = float((p.get("liquidity") or {}).get("usd") or 0)
                if addr and p_usd:
                    if addr not in best_by_addr or liq > best_by_addr[addr][1]:
                        best_by_addr[addr] = (float(p_usd), liq)
            for addr, (p_val, _) in best_by_addr.items():
                price_map[addr] = p_val
        except Exception as e:
            log.warning("DexScreener 批量查价异常: %s", e)

    return price_map


def _fetch_single_fallback_price(coin_id: str, symbol: str):
    headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    if config.COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = config.COINGECKO_API_KEY

    if coin_id and not str(coin_id).startswith("dex_"):
        try:
            res = _SESSION.get(
                f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd",
                headers=headers,
                timeout=10,
            ).json()
            price = res.get(coin_id, {}).get("usd")
            if price:
                return float(price)
        except Exception:
            pass

    if symbol:
        try:
            d_res = _SESSION.get(
                f"https://api.dexscreener.com/latest/dex/search?q={requests.utils.quote(symbol)}",
                timeout=10,
            ).json()
            pairs = [
                p for p in (d_res.get("pairs") or [])
                if ((p.get("baseToken") or {}).get("symbol") or "").upper() == symbol.upper()
            ]
            if pairs:
                best_p = max(pairs, key=lambda x: float((x.get("liquidity") or {}).get("usd") or 0))
                p_usd = best_p.get("priceUsd")
                if p_usd:
                    return float(p_usd)
        except Exception:
            pass
    return None


def _clamp(val, low, high):
    return round(max(low, min(high, float(val))), 2)


def _age_bucket(found_at_str: str) -> str:
    if not found_at_str:
        return "未知窗口"
    try:
        dt = datetime.strptime(found_at_str[:16], "%Y-%m-%d %H:%M")
        hours = (datetime.now() - dt).total_seconds() / 3600.0
        if hours <= 24:
            return "24h内"
        if hours <= 72:
            return "24h~72h"
        return "72h+"
    except Exception:
        return "未知窗口"


def compute_portfolio_metrics(rois: list) -> dict:
    """计算胜率、平均收益、盈亏比 (Payoff Ratio) 与单笔期望收益 (Expectancy)"""
    if not rois:
        return {
            "win_rate_pct": 0.0,
            "avg_roi_pct": 0.0,
            "payoff_ratio": 1.0,
            "expectancy_pct": 0.0,
        }
    wins = [r for r in rois if r >= 5.0]
    losses = [r for r in rois if r < 0.0]
    win_rate = len(wins) / len(rois)
    loss_rate = len(losses) / len(rois)

    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss_abs = (abs(sum(losses)) / len(losses)) if losses else 1.0
    payoff_ratio = round(avg_win / max(avg_loss_abs, 1.0), 2) if wins else 0.5
    expectancy = round(win_rate * avg_win - loss_rate * avg_loss_abs, 2)

    return {
        "win_rate_pct": round(win_rate * 100, 1),
        "avg_roi_pct": round(sum(rois) / len(rois), 2),
        "payoff_ratio": payoff_ratio,
        "expectancy_pct": expectancy,
    }


def run():
    log.info("[Job3 V7.0] 启动类脑级策略归因、盈亏比核算与自主进化引擎...")
    local_data = notifier.load_local_db()
    evo_state = local_data.get("evolution_state") or copy.deepcopy(config.DEFAULT_EVOLUTION_STATE)
    projects = [normalize_project(p) for p in (local_data.get("projects") or [])]

    alpha_records = feishu_db.get_records(config.TABLE_ID_ALPHA) if config.TABLE_ID_ALPHA else []

    all_contracts = [p["contract"] for p in projects if p["contract"]]
    for r in alpha_records[:15]:
        c_addr = _safe_str((r.get("fields") or {}).get("合约地址"))
        if c_addr:
            all_contracts.append(c_addr)

    batch_prices = _batch_fetch_dexscreener_prices(list(set(all_contracts)))

    fallback_targets = {}
    for p in projects:
        c_addr = p["contract"].lower()
        if p["recommended_price"] > 0 and p["symbol"] and (not c_addr or c_addr not in batch_prices):
            cid = _safe_str(p.get("coingecko_id") or p.get("id"))
            fallback_targets[(cid, p["symbol"])] = None

    if fallback_targets:
        with ThreadPoolExecutor(max_workers=4) as pool:
            keys = list(fallback_targets.keys())
            vals = list(pool.map(lambda k: _fetch_single_fallback_price(k[0], k[1]), keys))
            for k, v in zip(keys, vals):
                fallback_targets[k] = v

    performance_summary = []
    rois = []
    type_buckets = {}
    best_pick = ("暂无", -999.0)
    worst_pick = ("暂无", 999.0)

    for p in projects:
        sym = p["symbol"]
        entry_price = p["recommended_price"] or p["price"]
        if entry_price <= 0 or not sym:
            continue

        c_addr = p["contract"].lower()
        cid = _safe_str(p.get("coingecko_id") or p.get("id"))
        live_price = batch_prices.get(c_addr) or fallback_targets.get((cid, sym))

        if live_price and live_price > 0:
            roi = round((live_price - entry_price) / entry_price * 100, 2)
            p["live_price"] = live_price
            p["live_roi_pct"] = roi

            peak_price = max(p["peak_price"], live_price, entry_price)
            p["peak_price"] = peak_price
            peak_roi = round((peak_price - entry_price) / entry_price * 100, 2)
            p["max_drawdown_pct"] = round(min(p["max_drawdown_pct"], min(0.0, roi)), 2)

            rois.append(roi)
            type_buckets.setdefault(p["project_type"], []).append(roi)

            if roi > best_pick[1]:
                best_pick = (f"${sym} ({roi:+.1f}%)", roi)
            if roi < worst_pick[1]:
                worst_pick = (f"${sym} ({roi:+.1f}%)", roi)

            bucket = _age_bucket(p["found_at"])
            outcome_tag = "🏆盈利金狗" if roi >= 10 else ("🩸追高回撤/亏损" if roi <= -6 else "⏳震荡蓄势")
            performance_summary.append(
                f"- [{outcome_tag}|{bucket}] ${sym} ({p['project_type']}): 当前 {roi:+.2f}% (峰值 {peak_roi:+.1f}% / 回撤 {p['max_drawdown_pct']:+.1f}%) | "
                f"入选24h涨幅: {p['chg_24h']:+.1f}% | 市值: ${p['mc_wan']:.1f}万 | 买盘: {p['buy_ratio']:.1f}% | 窗口: {p['entry_timing']}"
            )

    for r in alpha_records[:15]:
        fields = r.get("fields", {})
        coin_id = _safe_str(fields.get("项目ID"))
        symbol = _safe_str(fields.get("代币符号"))
        contract_addr = _safe_str(fields.get("合约地址")).lower()
        old_price = _safe_float(fields.get("推荐时价格($)") or fields.get("推荐时价格"), 0.0)
        if old_price <= 0 or (not contract_addr and not symbol):
            continue
        new_price = batch_prices.get(contract_addr) or _fetch_single_fallback_price(coin_id, symbol)
        if new_price and new_price > 0:
            roi = round((new_price - old_price) / old_price * 100, 2)
            prev_peak = _safe_float(fields.get("最高涨幅(%)"), 0.0)
            feishu_db.update_record(
                config.TABLE_ID_ALPHA,
                r["record_id"],
                {
                    "实时价格($)": new_price,
                    "当前盈亏(%)": roi,
                    "最高涨幅(%)": max(prev_peak, roi),
                },
            )

    tz_bj = timezone(timedelta(hours=8))
    now_str = datetime.now(tz_bj).strftime("%Y-%m-%d %H:%M")

    if not performance_summary:
        log.info("尚无历史持仓样本可回测，初始化 V7.0 进化参数。")
        local_data["projects"] = projects
        local_data["evolution_state"] = evo_state
        notifier.save_local_db(local_data)
        return

    metrics = compute_portfolio_metrics(rois)
    attribution_lines = []
    for p_type, vals in type_buckets.items():
        m = compute_portfolio_metrics(vals)
        attribution_lines.append(f"{p_type}: {len(vals)}笔, 胜率{m['win_rate_pct']}%, 均益{m['avg_roi_pct']:+.1f}%, 盈亏比{m['payoff_ratio']}")
    attribution_summary = " | ".join(attribution_lines)

    curr_guardrails = evo_state.get("guardrails") or config.DEFAULT_EVOLUTION_STATE["guardrails"]
    curr_weights = evo_state.get("weights") or config.DEFAULT_EVOLUTION_STATE["weights"]

    prompt = f"""
你是加密量化基金的首席进化架构师 (Self-Evolver Agent)。
目标：在实战中持续进行策略归因与自我迭代，追求**高胜率与高盈亏比（赔率）的完美平衡**！

【实盘回测核心指标】
- 回测样本：{len(rois)} 个 | 胜率：{metrics['win_rate_pct']}% | 平均收益：{metrics['avg_roi_pct']:+.2f}%
- 盈亏比 (Payoff Ratio)：{metrics['payoff_ratio']} | 单笔期望收益：{metrics['expectancy_pct']:+.2f}%
- 分类型归因：{attribution_summary}
- 最佳捕获：{best_pick[0]} | 最大回撤：{worst_pick[0]}

明细数据：
{chr(10).join(performance_summary[:18])}

当前风控闸门：{curr_guardrails}
当前五维权重：{curr_weights}

请深度归因并输出纯 JSON 格式：
1. 动态调整 `guardrails`（边界：max_meme_mc_wan 400~2000，max_narrative_mc_wan 1500~6000，max_24h_pump_limit 35~80，sweet_spot_24h_max 18~42，min_buy_ratio_pct 52.0~58.0，min_score_threshold 66.0~75.0）。
2. 微调 5 项评分权重（之和必须为 1.00）。
3. 提炼 3 条一针见血的 `tactical_rules`。

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
  "evolution_reason": "用90字以内总结本轮策略归因、盈亏比变化及参数进化逻辑",
  "tactical_rules": [
    "铁律1：...",
    "铁律2：...",
    "铁律3：..."
  ]
}}
"""
    raw_resp = llm_engine.ask_ai(prompt, role="evolver_agent", temperature=0.25, json_mode=True)
    parsed = llm_engine.extract_json(raw_resp)

    evolved_successfully = False
    if isinstance(parsed, dict) and isinstance(parsed.get("guardrails"), dict):
        g = parsed["guardrails"]
        evo_state["guardrails"] = {
            "max_meme_mc_wan": _clamp(g.get("max_meme_mc_wan", 1200), 400, 2000),
            "max_narrative_mc_wan": _clamp(g.get("max_narrative_mc_wan", 4000), 1500, 6000),
            "max_24h_pump_limit": _clamp(g.get("max_24h_pump_limit", 58), 35, 80),
            "sweet_spot_24h_max": _clamp(g.get("sweet_spot_24h_max", 32), 18, 42),
            "min_buy_ratio_pct": _clamp(g.get("min_buy_ratio_pct", 54.0), 52.0, 58.0),
            "min_score_threshold": _clamp(g.get("min_score_threshold", 68.5), 66.0, 75.0),
        }

        if isinstance(parsed.get("weights"), dict):
            w = parsed["weights"]
            keys = ["early_timing", "buy_pressure", "mc_odds", "track_heat", "fundamentals"]
            w_sum = sum(max(float(w.get(k, 0.2)), 0.0) for k in keys)
            if w_sum > 0:
                evo_state["weights"] = {
                    k: round(max(float(w.get(k, 0.2)), 0.0) / w_sum, 3) for k in keys
                }

        if parsed.get("evolution_reason"):
            evo_state["evolution_reason"] = str(parsed["evolution_reason"]).strip()
        if isinstance(parsed.get("tactical_rules"), list) and parsed["tactical_rules"]:
            evo_state["tactical_rules"] = [str(r) for r in parsed["tactical_rules"][:4]]

        evo_state["generation"] = int(evo_state.get("generation", 1)) + 1
        evolved_successfully = True
    else:
        log.warning("LLM 进化参数解析失败或未配置 API Key，保留当前 Gen #%s 参数，仅更新回测归因指标。", evo_state.get("generation", 1))

    evo_state["last_evolved_at"] = now_str
    evo_state["win_rate_pct"] = metrics["win_rate_pct"]
    evo_state["avg_roi_pct"] = metrics["avg_roi_pct"]
    evo_state["payoff_ratio"] = metrics["payoff_ratio"]
    evo_state["expectancy_pct"] = metrics["expectancy_pct"]
    evo_state["attribution_summary"] = attribution_summary
    evo_state["total_tested"] = len(rois)
    evo_state["best_pick"] = best_pick[0]
    evo_state["worst_pick"] = worst_pick[0]

    if evolved_successfully and config.TABLE_ID_CONFIG:
        cfg_records = feishu_db.get_records(config.TABLE_ID_CONFIG)
        if cfg_records:
            w_now = evo_state["weights"]
            feishu_w = {
                "价格安全权重": round(w_now.get("early_timing", 0.30) * 100),
                "营销背书权重": round(w_now.get("buy_pressure", 0.25) * 100),
                "市值赔率权重": round(w_now.get("mc_odds", 0.20) * 100),
                "赛道热度权重": round(w_now.get("track_heat", 0.15) * 100),
                "技术实力权重": round(w_now.get("fundamentals", 0.10) * 100),
            }
            feishu_db.update_record(config.TABLE_ID_CONFIG, cfg_records[0]["record_id"], feishu_w)

    local_data["projects"] = projects
    local_data["evolution_state"] = evo_state
    notifier.save_local_db(local_data)
    log.info(
        "[进化完成 -> Gen #%s] 胜率:%s%% | 盈亏比:%s | 期望:%+.2f%%",
        evo_state["generation"], metrics["win_rate_pct"], metrics["payoff_ratio"], metrics["expectancy_pct"],
    )


if __name__ == "__main__":
    run()
