# job3_self_evolver.py - V7.2 多源交叉验真查价、异常值熔断与科学统计进化引擎
from concurrent.futures import ThreadPoolExecutor
import copy
from datetime import datetime, timezone, timedelta
import statistics
import requests
import config
import feishu_db
import llm_engine
import notifier
from logger import get_logger
from models import normalize_project

log = get_logger("job3_self_evolver")
_SESSION = requests.Session()

GECKO_NETWORK_MAP = {
    "solana": "solana",
    "bsc": "bsc",
    "ethereum": "eth",
    "eth": "eth",
    "base": "base",
    "arbitrum": "arbitrum",
    "polygon": "polygon_pos",
    "optimism": "optimism",
    "avalanche": "avax",
    "avax": "avax",
}


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


def _batch_fetch_dexscreener_prices(items: list) -> dict:
    """
    批量查询 DexScreener 合约实时价格。
    严格按 (chain, contract.lower()) 精确匹配，并过滤掉流动性 < $1,000 的幽灵池/假池。
    返回: {(chain, contract_lower): (price_usd, liquidity_usd)}
    """
    price_map = {}
    targets = {}
    for it in items:
        chain = str(it.get("chain") or "").strip().lower()
        addr = str(it.get("contract") or "").strip()
        if chain and addr:
            targets[(chain, addr.lower())] = addr

    if not targets:
        return price_map

    unique_addrs = list(dict.fromkeys(targets.values()))
    for i in range(0, len(unique_addrs), 30):
        chunk = ",".join(unique_addrs[i : i + 30])
        try:
            resp = _SESSION.get(
                f"https://api.dexscreener.com/latest/dex/tokens/{chunk}",
                timeout=12,
            )
            if resp.status_code != 200:
                continue
            pairs = resp.json().get("pairs") or []
            for p in pairs:
                p_chain = str(p.get("chainId") or "").strip().lower()
                base_addr = str((p.get("baseToken") or {}).get("address") or "").strip().lower()
                p_usd = p.get("priceUsd")
                liq = float((p.get("liquidity") or {}).get("usd") or 0)
                if not p_chain or not base_addr or not p_usd or liq < 1000.0:
                    continue
                key = (p_chain, base_addr)
                if key in targets:
                    p_val = float(p_usd)
                    if p_val > 0 and (key not in price_map or liq > price_map[key][1]):
                        price_map[key] = (p_val, liq)
        except Exception as e:
            log.warning("DexScreener 批量查价异常: %s", e)

    return price_map


def _fetch_geckoterminal_token_price(chain: str, contract: str):
    """
    第二独立数据源：通过 GeckoTerminal Token API 查询链上实时价格，用于多方交叉验证或兜底。
    返回: (price_usd, reserve_usd) 或 None
    """
    net = GECKO_NETWORK_MAP.get(chain.lower().strip())
    if not net or not contract:
        return None
    try:
        resp = _SESSION.get(
            f"https://api.geckoterminal.com/api/v2/networks/{net}/tokens/{contract}",
            headers={"Accept": "application/json;version=20230302"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        attrs = (resp.json().get("data") or {}).get("attributes") or {}
        p_usd = attrs.get("price_usd")
        reserve = float(attrs.get("total_reserve_in_usd") or 0.0)
        if p_usd and float(p_usd) > 0:
            return (float(p_usd), reserve)
    except Exception:
        pass
    return None


def _fetch_coingecko_price(coin_id: str):
    """仅当标的没有合约地址时，使用 CoinGecko ID 兜底查价（严禁按 symbol 跨链模糊搜索）"""
    if not coin_id or str(coin_id).startswith("dex_"):
        return None
    headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    if config.COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = config.COINGECKO_API_KEY
    try:
        res = _SESSION.get(
            f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd",
            headers=headers,
            timeout=10,
        ).json()
        price = res.get(coin_id, {}).get("usd")
        if price and float(price) > 0:
            return float(price)
    except Exception:
        pass
    return None


def verify_and_resolve_price(
    symbol: str,
    chain: str,
    contract: str,
    coin_id: str,
    ref_price: float,
    dex_quote: tuple = None,
    gecko_quote: tuple = None,
) -> float:
    """
    多源价格交叉验真与异常值熔断：
    1. 优先比对 DexScreener 与 GeckoTerminal 双源报价；
    2. 若双源偏差 <= 25%，采信高流动性数据源；
    3. 若单源报价相对参考价出现 > 50倍暴涨或 > 99%暴跌的极端异常，必须有第二数据源交叉确认，否则拒收异常报价。
    """
    candidates = []
    if dex_quote and dex_quote[0] > 0:
        candidates.append(("DexScreener", dex_quote[0], dex_quote[1]))
    if gecko_quote and gecko_quote[0] > 0:
        candidates.append(("GeckoTerminal", gecko_quote[0], gecko_quote[1]))

    if len(candidates) == 2:
        (_, p1, l1), (_, p2, l2) = candidates[0], candidates[1]
        diff_ratio = abs(p1 - p2) / max(min(p1, p2), 1e-12)
        if diff_ratio <= 0.25:
            return p1 if l1 >= l2 else p2
        # 双源分歧较大时，优先采信与参考价量级更合理且流动性更高的一方
        if ref_price > 0:
            d1 = abs(p1 - ref_price) / ref_price
            d2 = abs(p2 - ref_price) / ref_price
            log.warning("[%s] 双源报价分歧 (Dex:$%.6f vs Gecko:$%.6f)，择优采用更稳健报价", symbol, p1, p2)
            return p1 if (l1 >= l2 and d1 <= 20.0) or d2 > 50.0 else p2
        return p1 if l1 >= l2 else p2

    if len(candidates) == 1:
        src_name, p_val, _ = candidates[0]
        if ref_price > 0:
            ratio = p_val / ref_price
            if ratio > 50.0 or ratio < 0.01:
                log.warning(
                    "[%s] 单源(%s)报价 $%.6f 相对参考价 $%.6f 偏离过大(%.1fx)，缺乏第二源交叉确认，已熔断拒收！",
                    symbol, src_name, p_val, ref_price, ratio,
                )
                return None
        return p_val

    # 仅在完全无合约地址时尝试 CoinGecko ID
    if not contract and coin_id:
        cg_p = _fetch_coingecko_price(coin_id)
        if cg_p and ref_price > 0 and 0.01 <= (cg_p / ref_price) <= 50.0:
            return cg_p
        return cg_p

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


def _classify_trend_status(roi: float, roi_history: list) -> str:
    if roi >= 25.0:
        return "主升浪"
    if roi >= 5.0:
        return "稳步走强"
    if len(roi_history) >= 2 and roi > roi_history[-2] and roi > -6.0:
        return "企稳反弹"
    if roi <= -8.0:
        return "破位回撤"
    return "窄幅震荡"


def compute_portfolio_metrics(rois: list) -> dict:
    """科学统计：使用缩尾保护避免极端异常值扭曲均值，并同时计算中位数与合理盈亏比"""
    if not rois:
        return {
            "win_rate_pct": 0.0,
            "avg_roi_pct": 0.0,
            "median_roi_pct": 0.0,
            "payoff_ratio": 1.0,
            "expectancy_pct": 0.0,
        }
    clean_rois = [max(-99.0, min(500.0, float(r))) for r in rois]
    wins = [r for r in clean_rois if r >= 5.0]
    losses = [r for r in clean_rois if r < 0.0]
    win_rate = len(wins) / len(clean_rois)
    loss_rate = len(losses) / len(clean_rois)

    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss_abs = (abs(sum(losses)) / len(losses)) if losses else 10.0
    payoff_ratio = round(min(10.0, avg_win / max(avg_loss_abs, 1.0)), 2) if wins else 0.5
    expectancy = round(win_rate * avg_win - loss_rate * avg_loss_abs, 2)

    return {
        "win_rate_pct": round(win_rate * 100, 1),
        "avg_roi_pct": round(sum(clean_rois) / len(clean_rois), 2),
        "median_roi_pct": round(statistics.median(clean_rois), 2),
        "payoff_ratio": payoff_ratio,
        "expectancy_pct": expectancy,
    }


def run():
    log.info("[Job3 V7.2] 启动多源交叉验真回测、异常值熔断与自主进化引擎...")
    local_data = notifier.load_local_db()
    evo_state = local_data.get("evolution_state") or copy.deepcopy(config.DEFAULT_EVOLUTION_STATE)
    projects = [normalize_project(p) for p in (local_data.get("projects") or [])]

    alpha_records = feishu_db.get_records(config.TABLE_ID_ALPHA) if config.TABLE_ID_ALPHA else []

    # 1. 批量从 DexScreener 获取精准 (chain, contract) 报价
    batch_items = [{"chain": p["chain"], "contract": p["contract"]} for p in projects if p["contract"]]
    for r in alpha_records[:15]:
        f = r.get("fields") or {}
        c_addr = _safe_str(f.get("合约地址"))
        c_chain = _safe_str(f.get("所在公链"), "solana").lower()
        if c_addr:
            batch_items.append({"chain": c_chain, "contract": c_addr})

    dex_quotes = _batch_fetch_dexscreener_prices(batch_items)

    # 2. 对未命中 DexScreener 或相对参考价波动 > 2倍的标的，并发拉取 GeckoTerminal 进行双源交叉验证
    gecko_targets = []
    for p in projects:
        key = (p["chain"].lower(), p["contract"].lower())
        entry_p = p["recommended_price"] or p["price"]
        if not p["contract"] or entry_p <= 0:
            continue
        dq = dex_quotes.get(key)
        needs_cross_check = (dq is None) or (dq[0] / entry_p > 3.0) or (dq[0] / entry_p < 0.33)
        if needs_cross_check:
            gecko_targets.append((key, p["chain"], p["contract"]))

    gecko_quotes = {}
    if gecko_targets:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda t: _fetch_geckoterminal_token_price(t[1], t[2]), gecko_targets))
            for (key, _, _), gq in zip(gecko_targets, results):
                if gq:
                    gecko_quotes[key] = gq

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

        # 清理历史遗留的异常脏极值（例如曾经被错价污染的 >50000% 记录）
        if p.get("peak_roi_pct", 0.0) > 5000.0 or (p["peak_price"] / entry_price) > 50.0:
            p["peak_price"] = entry_price
            p["peak_roi_pct"] = 0.0
            p["roi_history"] = [0.0]

        key = (p["chain"].lower(), p["contract"].lower())
        cid = _safe_str(p.get("coingecko_id") or p.get("id"))
        ref_p = p["live_price"] if (p["live_price"] > 0 and p["live_price"] / entry_price <= 50.0) else entry_price

        live_price = verify_and_resolve_price(
            symbol=sym,
            chain=p["chain"],
            contract=p["contract"],
            coin_id=cid,
            ref_price=ref_p,
            dex_quote=dex_quotes.get(key),
            gecko_quote=gecko_quotes.get(key),
        )

        if live_price and live_price > 0:
            roi = round((live_price - entry_price) / entry_price * 100, 2)
            p["live_price"] = live_price
            p["live_roi_pct"] = roi

            peak_price = max(p["peak_price"], live_price, entry_price)
            p["peak_price"] = peak_price
            peak_roi = round((peak_price - entry_price) / entry_price * 100, 2)
            p["peak_roi_pct"] = peak_roi
            p["max_drawdown_pct"] = round(min(p["max_drawdown_pct"], min(0.0, roi)), 2)

            hist = [x for x in (p.get("roi_history") or []) if isinstance(x, (int, float)) and abs(x) <= 5000.0]
            hist.append(roi)
            p["roi_history"] = hist[-12:]
            p["trend_status"] = _classify_trend_status(roi, p["roi_history"])

            rois.append(roi)
            type_buckets.setdefault(p["project_type"], []).append(roi)

            if roi > best_pick[1]:
                best_pick = (f"${sym} ({roi:+.1f}%)", roi)
            if roi < worst_pick[1]:
                worst_pick = (f"${sym} ({roi:+.1f}%)", roi)

            bucket = _age_bucket(p["found_at"])
            outcome_tag = "🏆盈利金狗" if roi >= 10 else ("🩸回撤亏损" if roi <= -6 else "⏳震荡蓄势")
            performance_summary.append(
                f"- [{outcome_tag}|{bucket}] ${sym} ({p['project_type']}): 当前 {roi:+.2f}% (峰值 {peak_roi:+.1f}% / 回撤 {p['max_drawdown_pct']:+.1f}%) | "
                f"入选24h涨幅: {p['chg_24h']:+.1f}% | 市值: ${p['mc_wan']:.1f}万 | 买盘: {p['buy_ratio']:.1f}%"
            )

    for r in alpha_records[:15]:
        fields = r.get("fields", {})
        coin_id = _safe_str(fields.get("项目ID"))
        symbol = _safe_str(fields.get("代币符号"))
        c_chain = _safe_str(fields.get("所在公链"), "solana").lower()
        contract_addr = _safe_str(fields.get("合约地址")).lower()
        old_price = _safe_float(fields.get("推荐时价格($)") or fields.get("推荐时价格"), 0.0)
        if old_price <= 0 or (not contract_addr and not coin_id):
            continue
        key = (c_chain, contract_addr)
        new_price = verify_and_resolve_price(
            symbol=symbol,
            chain=c_chain,
            contract=contract_addr,
            coin_id=coin_id,
            ref_price=old_price,
            dex_quote=dex_quotes.get(key),
            gecko_quote=gecko_quotes.get(key),
        )
        if new_price and new_price > 0:
            roi = round((new_price - old_price) / old_price * 100, 2)
            prev_peak = _safe_float(fields.get("最高涨幅(%)"), 0.0)
            if prev_peak > 5000.0:
                prev_peak = roi
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
        log.info("尚无有效回测样本，初始化 V7.2 进化参数。")
        local_data["projects"] = projects
        local_data["evolution_state"] = evo_state
        notifier.save_local_db(local_data)
        return

    metrics = compute_portfolio_metrics(rois)
    attribution_lines = []
    for p_type, vals in type_buckets.items():
        m = compute_portfolio_metrics(vals)
        attribution_lines.append(f"{p_type}: {len(vals)}笔, 胜率{m['win_rate_pct']}%, 中位{m['median_roi_pct']:+.1f}%, 盈亏比{m['payoff_ratio']}")
    attribution_summary = " | ".join(attribution_lines)

    curr_guardrails = evo_state.get("guardrails") or config.DEFAULT_EVOLUTION_STATE["guardrails"]
    curr_weights = evo_state.get("weights") or config.DEFAULT_EVOLUTION_STATE["weights"]

    prompt = f"""
你是加密量化基金的首席进化架构师 (Self-Evolver Agent)。
目标：在实战中持续进行策略归因与自我迭代，动态调整市值区间（初始 5万~500万）与弹性动量上限，追求**高胜率与高盈亏比（赔率）的完美平衡**！

【实盘回测核心指标】
- 回测样本：{len(rois)} 个 | 胜率：{metrics['win_rate_pct']}% | 均益：{metrics['avg_roi_pct']:+.2f}% | 中位数：{metrics['median_roi_pct']:+.2f}%
- 盈亏比 (Payoff Ratio)：{metrics['payoff_ratio']} | 单笔期望收益：{metrics['expectancy_pct']:+.2f}%
- 分类型归因：{attribution_summary}
- 最佳捕获：{best_pick[0]} | 最大回撤：{worst_pick[0]}

明细数据：
{chr(10).join(performance_summary[:18])}

当前风控闸门：{curr_guardrails}
当前五维权重：{curr_weights}

请深度归因并输出纯 JSON 格式：
1. 动态调整 `guardrails`（边界：min_mc_wan 3~25，max_meme_mc_wan 200~1500，max_narrative_mc_wan 300~2000，max_24h_pump_limit 50~250，sweet_spot_24h_max 25~65，min_buy_ratio_pct 51.0~58.0，min_score_threshold 65.0~75.0）。
2. 微调 5 项评分权重（之和必须为 1.00）。
3. 提炼 3 条一针见血的 `tactical_rules`。

{{
  "guardrails": {{
    "min_mc_wan": 5.0,
    "max_meme_mc_wan": 500.0,
    "max_narrative_mc_wan": 500.0,
    "max_24h_pump_limit": 120.0,
    "sweet_spot_24h_max": 48.0,
    "min_buy_ratio_pct": 53.0,
    "min_score_threshold": 68.0
  }},
  "weights": {{
    "early_timing": 0.30,
    "buy_pressure": 0.25,
    "mc_odds": 0.20,
    "track_heat": 0.15,
    "fundamentals": 0.10
  }},
  "evolution_reason": "用90字以内总结本轮策略归因、盈亏比变化及市值/动量参数自我反思调整逻辑",
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
            "min_mc_wan": _clamp(g.get("min_mc_wan", 5.0), 3.0, 25.0),
            "max_meme_mc_wan": _clamp(g.get("max_meme_mc_wan", 500.0), 200.0, 1500.0),
            "max_narrative_mc_wan": _clamp(g.get("max_narrative_mc_wan", 500.0), 300.0, 2000.0),
            "max_24h_pump_limit": _clamp(g.get("max_24h_pump_limit", 120.0), 50.0, 250.0),
            "sweet_spot_24h_max": _clamp(g.get("sweet_spot_24h_max", 48.0), 25.0, 65.0),
            "min_buy_ratio_pct": _clamp(g.get("min_buy_ratio_pct", 53.0), 51.0, 58.0),
            "min_score_threshold": _clamp(g.get("min_score_threshold", 68.0), 65.0, 75.0),
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
        log.warning("LLM 进化参数解析失败或未配置 API Key，保留当前 Gen #%s 参数，仅更新走势与回测归因。", evo_state.get("generation", 1))

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
        "[进化完成 -> Gen #%s] 胜率:%s%% | 中位:%+.1f%% | 盈亏比:%s",
        evo_state["generation"], metrics["win_rate_pct"], metrics["median_roi_pct"], metrics["payoff_ratio"],
    )


if __name__ == "__main__":
    run()