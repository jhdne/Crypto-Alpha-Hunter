from typing import Any, Dict


def _to_float(val: Any, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _to_int(val: Any, default: int = 0) -> int:
    if val is None or val == "":
        return default
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def project_unique_key(item: Dict[str, Any]) -> str:
    """Global unique identifier using chain + contract address (fallback to symbol)."""
    chain = str(item.get("chain") or "unknown").strip().lower()
    contract = str(item.get("contract") or item.get("contract_address") or "").strip().lower()
    if contract:
        return f"{chain}:{contract}"
    symbol = str(item.get("symbol") or "").strip().lower()
    return f"{chain}:{symbol}"


def normalize_project(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a project dictionary across V5/V6/V7 schemas into a single canonical format.
    """
    p = dict(raw or {})

    symbol = str(p.get("symbol") or "").strip().upper()
    name = str(p.get("name") or symbol).strip()
    chain = str(p.get("chain") or "solana").strip().lower()
    contract = str(p.get("contract") or p.get("contract_address") or "").strip()

    price = _to_float(p.get("price"), 0.0)
    recommended_price = _to_float(p.get("recommended_price"), price)
    live_price = _to_float(p.get("live_price"), price)

    mc_usd = _to_float(p.get("mc_usd"), 0.0)
    mc_wan = _to_float(p.get("mc_wan"), 0.0)
    if mc_wan <= 0 and p.get("market_cap") is not None:
        mc_wan = _to_float(p.get("market_cap"), 0.0)
    if mc_wan <= 0 and mc_usd > 0:
        mc_wan = round(mc_usd / 10000.0, 2)
    if mc_usd <= 0 and mc_wan > 0:
        mc_usd = round(mc_wan * 10000.0, 2)

    liq_usd = _to_float(p.get("liq_usd"), 0.0)
    liq_wan = _to_float(p.get("liq_wan"), 0.0)
    if liq_wan <= 0 and p.get("liquidity_wan") is not None:
        liq_wan = _to_float(p.get("liquidity_wan"), 0.0)
    if liq_wan <= 0 and liq_usd > 0:
        liq_wan = round(liq_usd / 10000.0, 2)

    vol_24h = _to_float(p.get("vol_24h"), 0.0)
    vol_wan = _to_float(p.get("vol_wan"), 0.0)
    if vol_wan <= 0 and vol_24h > 0:
        vol_wan = round(vol_24h / 10000.0, 2)

    turnover_24h = _to_float(p.get("turnover_24h"), 0.0)
    if turnover_24h <= 0 and mc_usd > 0 and vol_24h > 0:
        turnover_24h = round((vol_24h / mc_usd) * 100.0, 1)

    chg_1h = _to_float(p.get("chg_1h"), _to_float(p.get("change_1h"), 0.0))
    chg_6h = _to_float(p.get("chg_6h"), _to_float(p.get("change_6h"), 0.0))
    chg_24h = _to_float(p.get("chg_24h"), _to_float(p.get("change_24h"), 0.0))

    buys_24h = _to_int(p.get("buys_24h"), 0)
    sells_24h = _to_int(p.get("sells_24h"), 0)
    buy_ratio = _to_float(p.get("buy_ratio"), 50.0)

    score = _to_float(p.get("score"), _to_float(p.get("final_score"), 0.0))
    project_type = str(p.get("project_type") or p.get("opp_type") or "🌪️ 高波Meme")
    report = str(p.get("report") or p.get("ai_report") or "")
    found_at = str(p.get("found_at") or p.get("discovered_at") or "")
    catalyst = str(p.get("catalyst") or "")
    track = str(p.get("track") or "早期Alpha")
    entry_timing = str(p.get("entry_timing") or "🟢 早期启动")
    age_label = str(p.get("age_label") or "⚡ 早期标的")
    pool_age_hours = _to_float(p.get("pool_age_hours"), 48.0)

    live_roi_pct = _to_float(p.get("live_roi_pct"), 0.0)
    peak_price = _to_float(p.get("peak_price"), max(recommended_price, live_price))
    max_drawdown_pct = _to_float(p.get("max_drawdown_pct"), 0.0)

    # V7.0 多维交叉验证与基本面穿透字段
    cv_score = _to_float(p.get("cv_score"), 65.0)
    cv_signals = p.get("cv_signals") if isinstance(p.get("cv_signals"), list) else []
    cv_confidence = str(p.get("cv_confidence") or "中置信度")
    mc_fdv_ratio = _to_float(p.get("mc_fdv_ratio"), 0.0)
    ath_drop = _to_float(p.get("ath_drop"), 0.0)
    commits_4w = _to_int(p.get("commits_4w"), 0)
    vc_hits = p.get("vc_hits") if isinstance(p.get("vc_hits"), list) else []
    position_tier = str(p.get("position_tier") or "轻仓试错(1-2%)")
    stop_loss_pct = _to_float(p.get("stop_loss_pct"), -18.0)
    take_profit_pct = _to_float(p.get("take_profit_pct"), 60.0)

    dex_url = str(p.get("dex_url") or "")
    if not dex_url:
        dex_url = (
            f"https://dexscreener.com/{chain}/{contract}"
            if contract
            else f"https://dexscreener.com/search?q={symbol}"
        )

    p.update({
        "name": name,
        "symbol": symbol,
        "chain": chain,
        "contract": contract,
        "price": price,
        "recommended_price": recommended_price,
        "live_price": live_price,
        "peak_price": peak_price,
        "live_roi_pct": live_roi_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "mc_usd": mc_usd,
        "mc_wan": mc_wan,
        "liq_usd": liq_usd,
        "liq_wan": liq_wan,
        "vol_24h": vol_24h,
        "vol_wan": vol_wan,
        "turnover_24h": turnover_24h,
        "chg_1h": chg_1h,
        "chg_6h": chg_6h,
        "chg_24h": chg_24h,
        "buys_24h": buys_24h,
        "sells_24h": sells_24h,
        "buy_ratio": buy_ratio,
        "pool_age_hours": pool_age_hours,
        "age_label": age_label,
        "score": score,
        "project_type": project_type,
        "track": track,
        "entry_timing": entry_timing,
        "catalyst": catalyst,
        "report": report,
        "found_at": found_at,
        "dex_url": dex_url,
        "cv_score": cv_score,
        "cv_signals": cv_signals,
        "cv_confidence": cv_confidence,
        "mc_fdv_ratio": mc_fdv_ratio,
        "ath_drop": ath_drop,
        "commits_4w": commits_4w,
        "vc_hits": vc_hits,
        "position_tier": position_tier,
        "stop_loss_pct": stop_loss_pct,
        "take_profit_pct": take_profit_pct,
    })
    return p
