# notifier.py - V7.1 机构专业版量化投研终端（今日聚焦 · 历史按日折叠走势跟踪 · SVG Sparkline）
import html
import json
import os
from datetime import datetime, timezone, timedelta
from config import (
    FEISHU_APP_ID,
    FEISHU_DASHBOARD_URL,
    LLM_API_KEYS,
    DEFAULT_EVOLUTION_STATE,
)
from feishu_db import FeishuDB
from logger import get_logger
from models import normalize_project

log = get_logger("notifier")
LOCAL_DB_PATH = "docs/alpha_db.json"
LATEST_ALERT_PATH = "docs/latest_alert.json"


def _esc(val) -> str:
    return html.escape(str(val or ""), quote=True)


def _safe_url(url: str, fallback: str = "#") -> str:
    u = str(url or "").strip()
    if u.startswith(("https://", "http://")):
        return html.escape(u, quote=True)
    return fallback


def _fmt_price(val: float) -> str:
    if val <= 0:
        return "$0.00"
    if val < 0.0001:
        return f"${val:.8f}"
    if val < 0.01:
        return f"${val:.6f}"
    return f"${val:.4f}"


def _build_sparkline_svg(roi_history: list, current_roi: float) -> str:
    """生成轻量级 SVG 走势折线图，直观展示历史扫描标的后续走势"""
    pts = [float(x) for x in (roi_history or []) if isinstance(x, (int, float))]
    if not pts:
        pts = [0.0, float(current_roi)]
    elif len(pts) == 1:
        pts = [0.0, pts[0]]

    w, h = 84, 24
    mn, mx = min(pts), max(pts)
    span = max(mx - mn, 1.0)
    coords = []
    for idx, val in enumerate(pts):
        x = round(idx * (w / max(len(pts) - 1, 1)), 1)
        y = round(h - 3 - ((val - mn) / span) * (h - 6), 1)
        coords.append(f"{x},{y}")

    stroke = "#10b981" if pts[-1] >= 0 else "#f43f5e"
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" class="inline-block align-middle">'
        f'<polyline fill="none" stroke="{stroke}" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" points="{" ".join(coords)}" />'
        f"</svg>"
    )


def load_local_db():
    if os.path.exists(LOCAL_DB_PATH):
        try:
            with open(LOCAL_DB_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            log.warning("读取本地数据库失败: %s", e)
    return {
        "updated_at": "",
        "api_status": {},
        "evolution_state": DEFAULT_EVOLUTION_STATE,
        "hot_keywords": [],
        "vc_And_news": [],
        "tracks": [],
        "allocation_matrix": [],
        "projects": [],
    }


def save_local_db(data):
    os.makedirs("docs", exist_ok=True)
    tz_bj = timezone(timedelta(hours=8))
    data["updated_at"] = datetime.now(tz_bj).strftime("%Y-%m-%d %H:%M:%S (UTC+8)")
    with open(LOCAL_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _normalize_news_items(local_data):
    raw_news = local_data.get("vc_And_news") or local_data.get("vc_news") or []
    normalized = []
    for item in raw_news:
        if isinstance(item, dict):
            normalized.append({
                "type": str(item.get("type", "情报")),
                "title": str(item.get("title", "")),
            })
        elif isinstance(item, str):
            if "热搜" in item:
                normalized.append({"type": "热搜", "title": item})
            elif "融资" in item or "VC" in item:
                normalized.append({"type": "VC融资", "title": item})
            elif "TVL" in item:
                normalized.append({"type": "TVL异动", "title": item})
            else:
                normalized.append({"type": "快讯", "title": item})
    return normalized


def _render_project_card(p: dict, now_str: str) -> str:
    score = p["score"]
    score_cls = (
        "bg-emerald-500/15 text-emerald-300 border-emerald-500/40"
        if score >= 80
        else "bg-sky-500/15 text-sky-300 border-sky-500/40"
    )

    opp_type = p["project_type"]
    if "Meme" in opp_type or "金狗" in opp_type:
        type_cls = "bg-amber-500/10 text-amber-300 border-amber-500/30"
        filter_tag = "meme"
    elif "龙头" in opp_type:
        type_cls = "bg-emerald-500/10 text-emerald-300 border-emerald-500/30"
        filter_tag = "leader"
    elif "异动" in opp_type or "黑马" in opp_type:
        type_cls = "bg-violet-500/10 text-violet-300 border-violet-500/30"
        filter_tag = "breakout"
    else:
        type_cls = "bg-sky-500/10 text-sky-300 border-sky-500/30"
        filter_tag = "value"

    chain = p["chain"].upper()
    contract_addr = p["contract"]
    short_addr = f"{contract_addr[:6]}...{contract_addr[-4:]}" if len(contract_addr) > 12 else contract_addr

    chg_1h = p["chg_1h"]
    chg_24h = p["chg_24h"]
    c1h_cls = "text-emerald-400" if chg_1h >= 0 else "text-rose-400"
    c24_cls = "text-emerald-400" if chg_24h >= 0 else "text-rose-400"

    live_roi = p["live_roi_pct"]
    roi_cls = "text-emerald-400" if live_roi >= 0 else "text-rose-400"
    roi_chip = (
        f'<span class="font-mono text-[11px] px-2 py-0.5 rounded border border-slate-700 bg-slate-900 {roi_cls}">实盘 {live_roi:+.1f}%</span>'
        if live_roi != 0
        else ""
    )

    buys_24h, sells_24h = p["buys_24h"], p["sells_24h"]
    buy_ratio = p["buy_ratio"]
    tx_display = (
        f"{buys_24h}B / {sells_24h}S ({buy_ratio:.1f}%)"
        if (buys_24h + sells_24h) > 0
        else f"买盘 {buy_ratio:.1f}%"
    )

    symbol_clean = p["symbol"]
    dex_url = _safe_url(p["dex_url"], f"https://dexscreener.com/search?q={_esc(symbol_clean)}")
    cg_id = p.get("coingecko_id") or p.get("id") or ""
    cg_url = _safe_url(
        f"https://www.coingecko.com/en/coins/{cg_id}"
        if cg_id and not str(cg_id).startswith("dex_")
        else f"https://www.coingecko.com/en/search?query={symbol_clean}"
    )
    x_url = _safe_url(f"https://x.com/search?q=%24{symbol_clean}&src=typed_query&f=live")

    return f"""
    <article class="project-card inst-card rounded-xl p-5 flex flex-col justify-between transition hover:border-slate-600/80" data-type="{filter_tag}">
        <div>
            <div class="flex items-start justify-between gap-3 mb-3">
                <div class="min-w-0">
                    <div class="flex items-center gap-2 flex-wrap">
                        <span class="text-lg font-bold text-slate-100 tracking-tight font-mono">${_esc(symbol_clean)}</span>
                        <span class="text-[11px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">{_esc(chain)}</span>
                        <span class="text-[11px] px-2 py-0.5 rounded border {type_cls}">{_esc(opp_type)}</span>
                        <span class="text-[11px] px-2 py-0.5 rounded bg-slate-800/90 text-slate-300 border border-slate-700/80">{_esc(p['cv_confidence'])}</span>
                        {roi_chip}
                    </div>
                    <div class="flex items-center gap-2 mt-1.5 text-xs text-slate-400 flex-wrap">
                        <span class="text-slate-200 font-medium">{_esc(p['name'])}</span>
                        <span>·</span>
                        <span>{_esc(p['track'])}</span>
                        <span>·</span>
                        <span class="text-emerald-400">{_esc(p['entry_timing'])}</span>
                        <span>·</span>
                        <span>{_esc(p['age_label'])}</span>
                    </div>
                </div>
                <div class="text-right shrink-0">
                    <div class="font-mono text-sm font-bold px-2.5 py-1 rounded-lg border {score_cls}">{score:.1f}</div>
                    <div class="text-[10px] text-slate-500 mt-1">{_esc(p['position_tier'])}</div>
                </div>
            </div>

            <div class="grid grid-cols-4 gap-2.5 py-2.5 px-3 rounded-lg bg-[#090d16] border border-slate-800/90 text-xs font-mono mb-3">
                <div>
                    <span class="text-[10px] text-slate-500 font-sans block">建仓参考价</span>
                    <span class="text-slate-100 font-semibold">{_fmt_price(p['price'])}</span>
                </div>
                <div>
                    <span class="text-[10px] text-slate-500 font-sans block">1h / 24h 动量</span>
                    <span class="font-semibold"><span class="{c1h_cls}">{chg_1h:+.1f}%</span> <span class="text-slate-600">/</span> <span class="{c24_cls}">{chg_24h:+.1f}%</span></span>
                </div>
                <div>
                    <span class="text-[10px] text-slate-500 font-sans block">流通市值 / LP</span>
                    <span class="text-slate-200 font-semibold">${p['mc_wan']:.1f}W <span class="text-slate-500">/ ${p['liq_wan']:.1f}W</span></span>
                </div>
                <div>
                    <span class="text-[10px] text-slate-500 font-sans block">买卖盘 / 换手</span>
                    <span class="text-slate-200">{tx_display}</span>
                </div>
            </div>

            <div class="text-xs text-slate-300 bg-[#0a0f1a] rounded-lg p-3 border border-slate-800/80 leading-relaxed mb-2">
                <div class="text-[11px] text-amber-300/90 font-medium mb-1">催化逻辑：{_esc(p['catalyst'] or '链上早期量价启动')}</div>
                <div class="text-slate-300">{_esc(p['report'])}</div>
            </div>
        </div>

        <div class="pt-2.5 border-t border-slate-800/80 flex items-center justify-between text-[11px] text-slate-500">
            <div class="flex items-center gap-2 font-mono">
                <span>{_esc(p['found_at'] or now_str[:16])}</span>
                {f'<span class="text-slate-600">|</span><span title="{_esc(contract_addr)}">{_esc(short_addr)}</span>' if short_addr else ''}
            </div>
            <div class="flex items-center gap-1.5">
                <a href="{dex_url}" target="_blank" rel="noopener noreferrer" class="px-2 py-1 rounded bg-slate-800/80 hover:bg-slate-700 text-emerald-300 transition">DEX ↗</a>
                <a href="{x_url}" target="_blank" rel="noopener noreferrer" class="px-2 py-1 rounded bg-slate-800/80 hover:bg-slate-700 text-sky-300 transition">𝕏 ↗</a>
                <a href="{cg_url}" target="_blank" rel="noopener noreferrer" class="px-2 py-1 rounded bg-slate-800/80 hover:bg-slate-700 text-indigo-300 transition">CG ↗</a>
            </div>
        </div>
    </article>
    """


def _render_history_archive(history_by_date: dict) -> str:
    if not history_by_date:
        return '<div class="inst-card rounded-xl p-6 text-center text-xs text-slate-500">暂无历史日期归档数据，随着每日 1H 扫描运行将自动按日归档并跟踪走势。</div>'

    blocks = []
    for date_str in sorted(history_by_date.keys(), reverse=True):
        items = history_by_date[date_str]
        rois = [p["live_roi_pct"] for p in items]
        avg_roi = round(sum(rois) / len(rois), 1) if rois else 0.0
        wins = sum(1 for r in rois if r >= 5.0)
        win_rate = round((wins / len(rois)) * 100, 1) if rois else 0.0
        avg_score = round(sum(p["score"] for p in items) / len(items), 1) if items else 0.0
        avg_cls = "text-emerald-400" if avg_roi >= 0 else "text-rose-400"

        rows_html = ""
        for p in items:
            roi = p["live_roi_pct"]
            peak_roi = p["peak_roi_pct"]
            dd = p["max_drawdown_pct"]
            roi_cls = "text-emerald-400" if roi >= 0 else "text-rose-400"
            spark_svg = _build_sparkline_svg(p.get("roi_history", []), roi)
            trend_st = p.get("trend_status", "待跟踪")
            if "主升" in trend_st or "走强" in trend_st or "反弹" in trend_st:
                st_cls = "bg-emerald-500/10 text-emerald-300 border-emerald-500/30"
            elif "回撤" in trend_st:
                st_cls = "bg-rose-500/10 text-rose-300 border-rose-500/30"
            else:
                st_cls = "bg-slate-800 text-slate-300 border-slate-700"

            dex_url = _safe_url(p["dex_url"])
            rows_html += f"""
            <tr class="border-t border-slate-800/80 hover:bg-slate-800/30 transition">
                <td class="py-2.5 px-3">
                    <div class="flex items-center gap-2">
                        <span class="font-mono font-bold text-slate-100">${_esc(p['symbol'])}</span>
                        <span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">{_esc(p['chain'].upper())}</span>
                    </div>
                    <div class="text-[11px] text-slate-500 truncate max-w-[160px]">{_esc(p['track'])} · ${_esc(round(p['mc_wan'], 1))}W</div>
                </td>
                <td class="py-2.5 px-3 font-mono font-bold text-sky-300">{p['score']:.1f}</td>
                <td class="py-2.5 px-3 font-mono text-xs">
                    <div class="text-slate-400">{_fmt_price(p['recommended_price'] or p['price'])}</div>
                    <div class="text-slate-200">→ {_fmt_price(p['live_price'])}</div>
                </td>
                <td class="py-2.5 px-3">
                    <div class="flex items-center gap-2">
                        {spark_svg}
                        <span class="text-[11px] px-2 py-0.5 rounded border {st_cls}">{_esc(trend_st)}</span>
                    </div>
                </td>
                <td class="py-2.5 px-3 font-mono text-xs">
                    <div class="font-bold {roi_cls}">{roi:+.1f}%</div>
                    <div class="text-[10px] text-slate-500">峰 {peak_roi:+.1f}% / 撤 {dd:+.1f}%</div>
                </td>
                <td class="py-2.5 px-3 text-right">
                    <a href="{dex_url}" target="_blank" rel="noopener noreferrer" class="text-xs px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-emerald-300 transition">K线 ↗</a>
                </td>
            </tr>
            """

        blocks.append(f"""
        <details class="history-day inst-card rounded-xl overflow-hidden group">
            <summary class="cursor-pointer list-none px-4 py-3.5 flex flex-wrap items-center justify-between gap-3 hover:bg-slate-800/30 transition select-none">
                <div class="flex items-center gap-3">
                    <span class="font-mono text-sm font-bold text-slate-100">{_esc(date_str)}</span>
                    <span class="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">{len(items)} 个标的</span>
                    <span class="text-xs text-slate-400 font-mono">平均打分 {avg_score:.1f}</span>
                </div>
                <div class="flex items-center gap-4 text-xs font-mono">
                    <span class="text-slate-400">胜率 <strong class="text-slate-200">{win_rate:.1f}%</strong></span>
                    <span class="text-slate-400">平均收益 <strong class="{avg_cls}">{avg_roi:+.1f}%</strong></span>
                    <span class="text-slate-400 group-open:rotate-180 transition-transform">▾</span>
                </div>
            </summary>
            <div class="border-t border-slate-800/80 overflow-x-auto bg-[#090d16]">
                <table class="w-full text-left text-xs">
                    <thead class="text-[11px] text-slate-500 uppercase bg-[#0b101b]">
                        <tr>
                            <th class="py-2 px-3 font-medium">标的 / 市值</th>
                            <th class="py-2 px-3 font-medium">扫描打分</th>
                            <th class="py-2 px-3 font-medium">推荐价 → 现价</th>
                            <th class="py-2 px-3 font-medium">走势跟踪</th>
                            <th class="py-2 px-3 font-medium">实时盈亏 / 极值</th>
                            <th class="py-2 px-3 font-medium text-right">详情</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>
        </details>
        """)
    return "\n".join(blocks)


def build_dashboard(latest_alert_title="", latest_alert_md=""):
    log.info("正在构建机构专业版投研看板 V7.1 (docs/index.html)...")
    local_data = load_local_db()
    feishu_ok = False

    if FEISHU_APP_ID:
        try:
            db = FeishuDB()
            if db.token:
                feishu_ok = True
        except Exception as e:
            log.warning("飞书状态检查异常: %s", e)

    tz_bj = timezone(timedelta(hours=8))
    now_bj = datetime.now(tz_bj)
    today_str = now_bj.strftime("%Y-%m-%d")
    now_str = local_data.get("updated_at") or now_bj.strftime("%Y-%m-%d %H:%M:%S (UTC+8)")

    evo = local_data.get("evolution_state") or DEFAULT_EVOLUTION_STATE
    guardrails = evo.get("guardrails") or DEFAULT_EVOLUTION_STATE["guardrails"]
    tactical_rules = evo.get("tactical_rules") or DEFAULT_EVOLUTION_STATE["tactical_rules"]

    hot_keywords = local_data.get("hot_keywords") or local_data.get("keywords") or []
    vc_and_news = _normalize_news_items(local_data)
    tracks_data = local_data.get("tracks", [])
    allocation_matrix = local_data.get("allocation_matrix", [])
    all_projects = [normalize_project(p) for p in (local_data.get("projects") or [])]

    # 按北京时间日期切分：当日标的 vs 历史归档
    today_projects = []
    history_by_date = {}
    for p in all_projects:
        d_str = (p.get("found_at") or "")[:10]
        if d_str == today_str:
            today_projects.append(p)
        else:
            bucket_date = d_str if len(d_str) == 10 else "早期归档"
            history_by_date.setdefault(bucket_date, []).append(p)

    alert_payload = local_data.get("alert") or {}
    if latest_alert_title or latest_alert_md:
        alert_payload = {
            "title": latest_alert_title or alert_payload.get("title", "系统状态同步"),
            "content": latest_alert_md or alert_payload.get("content", ""),
            "time": now_str,
            "today_count": len(today_projects),
            "history_count": len(all_projects) - len(today_projects),
        }
    os.makedirs("docs", exist_ok=True)
    with open(LATEST_ALERT_PATH, "w", encoding="utf-8") as f:
        json.dump(alert_payload, f, ensure_ascii=False, indent=2)

    # 顶部紧凑状态指示灯
    engine_pills = [
        ("GLM/Groq AI", bool(LLM_API_KEYS.get("glm") or LLM_API_KEYS.get("groq"))),
        ("1H 扫描雷达", True),
        ("多维交叉验证", True),
        ("飞书同步" if feishu_ok else "本地闭环", True),
    ]
    pills_html = "".join([
        f'<span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] bg-slate-900 border border-slate-800 text-slate-300">'
        f'<span class="w-1.5 h-1.5 rounded-full {"bg-emerald-400" if ok else "bg-amber-400"}"></span>{_esc(name)}</span>'
        for name, ok in engine_pills
    ])

    avg_roi = float(evo.get("avg_roi_pct", 0.0))
    roi_cls = "text-emerald-400" if avg_roi >= 0 else "text-rose-400"
    payoff_ratio = float(evo.get("payoff_ratio", 1.0))
    expectancy_pct = float(evo.get("expectancy_pct", 0.0))
    min_mc = float(guardrails.get("min_mc_wan", 5.0))
    max_mc = float(guardrails.get("max_meme_mc_wan", 500.0))

    rules_html = "".join([
        f'<li class="text-xs text-slate-300 flex items-start gap-2"><span class="text-emerald-400 font-mono">›</span><span>{_esc(r)}</span></li>'
        for r in tactical_rules[:3]
    ])

    alloc_html = "".join([
        f"""
        <div class="p-3 rounded-lg bg-[#090d16] border border-slate-800/90">
            <div class="flex items-center justify-between gap-2 mb-1.5">
                <span class="text-xs font-bold text-slate-100">{_esc(item.get('track', ''))}</span>
                <span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-sky-300">{_esc(item.get('ratio_hint', '50/50'))}</span>
            </div>
            <div class="text-[11px] text-slate-400 mb-1.5">{_esc(item.get('trend_thesis', ''))}</div>
            <div class="text-[11px] text-emerald-300/90">龙头：{_esc(item.get('leader', ''))}</div>
            <div class="text-[11px] text-amber-300/90">黑马：{_esc(item.get('dark_horse', ''))}</div>
        </div>
        """
        for item in allocation_matrix[:4]
    ]) or '<div class="text-xs text-slate-500">等待趋势推演任务更新配置清单...</div>'

    kw_html = "".join([
        f'<span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs bg-[#090d16] border border-slate-800 text-slate-200">'
        f'<span class="font-mono text-[10px] text-amber-300">{int(kw.get("heat", 85) or 85)}</span>{_esc(kw.get("keyword") or kw.get("word") or "")}</span>'
        for kw in hot_keywords[:8]
    ]) or '<span class="text-xs text-slate-500">等待热点扫描...</span>'

    news_html = "".join([
        f'<div class="flex items-start gap-2 py-1.5 border-b border-slate-800/70 last:border-0 text-xs">'
        f'<span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 shrink-0">{_esc(item.get("type", "情报"))}</span>'
        f'<span class="text-slate-300 leading-snug">{_esc(item.get("title", ""))}</span></div>'
        for item in vc_and_news[:6]
    ]) or '<div class="text-xs text-slate-500">暂无最新资金面与快讯</div>'

    tracks_html = "".join([
        f'<div class="px-3 py-2 rounded-lg bg-[#090d16] border border-slate-800/90 flex items-center justify-between text-xs">'
        f'<span class="text-slate-200 font-medium truncate">{_esc(t.get("name") or t.get("赛道名称") or "")}</span>'
        f'<span class="font-mono {"text-emerald-400" if float(t.get("change_24h") or 0) >= 0 else "text-rose-400"}">{float(t.get("change_24h") or 0):+.1f}%</span></div>'
        for t in tracks_data[:6]
    ])

    today_cards_html = (
        "\n".join(_render_project_card(p, now_str) for p in today_projects)
        if today_projects
        else f"""
        <div class="col-span-2 inst-card rounded-xl p-8 text-center">
            <div class="text-sm font-medium text-slate-300 mb-1">今日 ({_esc(today_str)}) 暂未触发符合 $5W~$500W 高赔率标准的标的</div>
            <div class="text-xs text-slate-500">系统每 1 小时自动扫描一次，宁缺毋滥；历史扫描标的与走势跟踪请在下方按日期展开查看。</div>
        </div>
        """
    )

    history_html = _render_history_archive(history_by_date)
    feishu_btn = (
        f'<a href="{_safe_url(FEISHU_DASHBOARD_URL)}" target="_blank" rel="noopener noreferrer" class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium border border-slate-700 transition">飞书控制台 ↗</a>'
        if FEISHU_DASHBOARD_URL
        else ""
    )

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Crypto Alpha Hunter V7.1 | 机构级全周期量化投研终端</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {{
            background-color: #080b12;
            color: #e2e8f0;
            font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            -webkit-font-smoothing: antialiased;
        }}
        .inst-card {{
            background-color: #0e1420;
            border: 1px solid rgba(148, 163, 184, 0.14);
        }}
        .font-mono {{
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-variant-numeric: tabular-nums;
        }}
        ::-webkit-scrollbar {{ width: 5px; height: 5px; }}
        ::-webkit-scrollbar-thumb {{ background: #334155; border-radius: 3px; }}
    </style>
</head>
<body class="min-h-screen pb-16">
    <header class="border-b border-slate-800/80 bg-[#080b12]/90 sticky top-0 z-50 backdrop-blur-md">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 py-3.5 flex flex-wrap items-center justify-between gap-3">
            <div class="flex items-center gap-3">
                <div class="w-8 h-8 rounded-lg bg-emerald-500/15 border border-emerald-500/40 flex items-center justify-center text-emerald-400 font-mono font-bold text-sm">α</div>
                <div>
                    <div class="flex items-center gap-2">
                        <h1 class="text-base font-bold text-slate-100 tracking-tight">Crypto Alpha Hunter</h1>
                        <span class="font-mono text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/30">V7.1 PRO</span>
                    </div>
                    <p class="text-[11px] text-slate-500">1H 高频全周期扫描 · 类脑自主进化 · 多维交叉验证</p>
                </div>
            </div>
            <div class="flex items-center gap-2 flex-wrap">
                {pills_html}
                <span class="font-mono text-[11px] text-slate-400 bg-slate-900 px-2.5 py-1 rounded-md border border-slate-800">{_esc(now_str)}</span>
                {feishu_btn}
            </div>
        </div>
    </header>

    <main class="max-w-7xl mx-auto px-4 sm:px-6 mt-6 space-y-6">
        <!-- Layer 1: 类脑进化与策略风控终端 -->
        <section class="inst-card rounded-xl p-5">
            <div class="flex flex-wrap items-center justify-between gap-2 pb-3 mb-4 border-b border-slate-800/80">
                <div class="flex items-center gap-2.5">
                    <span class="font-mono text-xs px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 font-semibold">GEN #{int(evo.get('generation', 1))}</span>
                    <h2 class="text-sm font-bold text-slate-100">自主进化风控中枢（动态参数与策略归因）</h2>
                </div>
                <span class="font-mono text-[11px] text-slate-500">上次进化: {_esc(evo.get('last_evolved_at', '待触发'))}</span>
            </div>

            <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-4 font-mono">
                <div class="p-3 rounded-lg bg-[#090d16] border border-slate-800/90">
                    <div class="text-[11px] text-slate-500 font-sans">实盘胜率</div>
                    <div class="text-base font-bold text-emerald-400 mt-0.5">{float(evo.get('win_rate_pct', 0)):.1f}% <span class="text-[11px] text-slate-500 font-normal">({int(evo.get('total_tested', 0))})</span></div>
                </div>
                <div class="p-3 rounded-lg bg-[#090d16] border border-slate-800/90">
                    <div class="text-[11px] text-slate-500 font-sans">均益 / 期望</div>
                    <div class="text-base font-bold {roi_cls} mt-0.5">{avg_roi:+.1f}% <span class="text-[11px] text-slate-500 font-normal">({expectancy_pct:+.1f}%)</span></div>
                </div>
                <div class="p-3 rounded-lg bg-[#090d16] border border-slate-800/90">
                    <div class="text-[11px] text-slate-500 font-sans">盈亏比</div>
                    <div class="text-base font-bold text-amber-300 mt-0.5">{payoff_ratio:.2f} : 1</div>
                </div>
                <div class="p-3 rounded-lg bg-[#090d16] border border-slate-800/90">
                    <div class="text-[11px] text-slate-500 font-sans">目标市值区间</div>
                    <div class="text-sm font-bold text-sky-300 mt-1">${min_mc:.0f}W ~ ${max_mc:.0f}W</div>
                </div>
                <div class="p-3 rounded-lg bg-[#090d16] border border-slate-800/90">
                    <div class="text-[11px] text-slate-500 font-sans">弹性动量参考</div>
                    <div class="text-sm font-bold text-slate-200 mt-1">+{float(guardrails.get('max_24h_pump_limit', 120)):.0f}% (结构过滤)</div>
                </div>
                <div class="p-3 rounded-lg bg-[#090d16] border border-slate-800/90">
                    <div class="text-[11px] text-slate-500 font-sans">最佳捕获</div>
                    <div class="text-xs font-bold text-amber-300 mt-1 truncate">{_esc(evo.get('best_pick', '暂无'))}</div>
                </div>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 pt-3 border-t border-slate-800/80">
                <div>
                    <div class="text-xs font-semibold text-slate-300 mb-1">策略归因与自我反思</div>
                    <p class="text-xs text-slate-400 leading-relaxed">{_esc(evo.get('evolution_reason', ''))}</p>
                    <p class="text-[11px] text-slate-500 mt-1 font-mono">归因明细：{_esc(evo.get('attribution_summary', '积累中'))}</p>
                </div>
                <div>
                    <div class="text-xs font-semibold text-slate-300 mb-1">当前生效执行铁律</div>
                    <ul class="space-y-1">{rules_html}</ul>
                </div>
            </div>
        </section>

        <!-- Layer 2: 趋势配置清单与多维情报 -->
        <section class="grid grid-cols-1 lg:grid-cols-12 gap-5">
            <div class="lg:col-span-7 inst-card rounded-xl p-5">
                <div class="flex items-center justify-between mb-3">
                    <h2 class="text-sm font-bold text-slate-100">趋势推演与前瞻配置清单（龙头 × 黑马）</h2>
                    <span class="text-[11px] text-slate-500">宏观轮动模型</span>
                </div>
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {alloc_html}
                </div>
            </div>
            <div class="lg:col-span-5 inst-card rounded-xl p-5 flex flex-col justify-between gap-4">
                <div>
                    <div class="flex items-center justify-between mb-2">
                        <h2 class="text-sm font-bold text-slate-100">叙事热词与轮动赛道</h2>
                        <span class="text-[11px] text-slate-500">多源共振</span>
                    </div>
                    <div class="flex flex-wrap gap-1.5 mb-3">{kw_html}</div>
                    <div class="grid grid-cols-2 gap-2">{tracks_html}</div>
                </div>
                <div>
                    <div class="text-xs font-semibold text-slate-300 mb-1.5">一级 VC / TVL 资金快讯</div>
                    <div class="max-h-36 overflow-y-auto pr-1">{news_html}</div>
                </div>
            </div>
        </section>

        <!-- Layer 3: 今日扫描 Alpha 标的池 -->
        <section>
            <div class="flex flex-wrap items-center justify-between gap-3 mb-3.5">
                <div>
                    <h2 class="text-base font-bold text-slate-100">今日 Alpha 狙击池 <span class="font-mono text-xs text-emerald-400 ml-1">{_esc(today_str)}</span></h2>
                    <p class="text-xs text-slate-500">仅展示今日新增捕获标的（每 1 小时刷新），历史标的已按日期归档至下方</p>
                </div>
                <div class="flex flex-wrap gap-1.5">
                    <button onclick="filterProjects('all', this)" class="filter-btn px-3 py-1 rounded-lg text-xs font-medium bg-slate-100 text-slate-900 transition">全部 ({len(today_projects)})</button>
                    <button onclick="filterProjects('meme', this)" class="filter-btn px-3 py-1 rounded-lg text-xs font-medium bg-slate-900 text-slate-300 border border-slate-800 hover:bg-slate-800 transition">早期 Meme</button>
                    <button onclick="filterProjects('breakout', this)" class="filter-btn px-3 py-1 rounded-lg text-xs font-medium bg-slate-900 text-slate-300 border border-slate-800 hover:bg-slate-800 transition">叙事黑马</button>
                    <button onclick="filterProjects('leader', this)" class="filter-btn px-3 py-1 rounded-lg text-xs font-medium bg-slate-900 text-slate-300 border border-slate-800 hover:bg-slate-800 transition">赛道龙头</button>
                    <button onclick="filterProjects('value', this)" class="filter-btn px-3 py-1 rounded-lg text-xs font-medium bg-slate-900 text-slate-300 border border-slate-800 hover:bg-slate-800 transition">价值击球区</button>
                </div>
            </div>
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {today_cards_html}
            </div>
        </section>

        <!-- Layer 4: 历史扫描归档与走势跟踪（默认折叠，点击展开） -->
        <section>
            <div class="flex items-center justify-between mb-3">
                <div>
                    <h2 class="text-base font-bold text-slate-100">历史扫描归档与走势跟踪</h2>
                    <p class="text-xs text-slate-500">按日期折叠隐藏，点击对应日期即可展开查看扫描打分、推荐后走势曲线与实时盈亏</p>
                </div>
                <span class="font-mono text-xs text-slate-500">{len(history_by_date)} 个历史交易日</span>
            </div>
            <div class="space-y-2.5">
                {history_html}
            </div>
        </section>
    </main>

    <script>
        function filterProjects(type, btnEl) {{
            const cards = document.querySelectorAll('.project-card');
            const btns = document.querySelectorAll('.filter-btn');
            btns.forEach(b => {{
                b.classList.remove('bg-slate-100', 'text-slate-900');
                b.classList.add('bg-slate-900', 'text-slate-300', 'border', 'border-slate-800');
            }});
            if (btnEl) {{
                btnEl.classList.remove('bg-slate-900', 'text-slate-300', 'border', 'border-slate-800');
                btnEl.classList.add('bg-slate-100', 'text-slate-900');
            }}
            cards.forEach(card => {{
                card.style.display = (type === 'all' || card.dataset.type === type) ? 'flex' : 'none';
            }});
        }}
    </script>
</body>
</html>
"""
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    log.info("机构专业版投研看板 V7.1 已生成: docs/index.html")


def send_wechat(title, md_content):
    log.info("更新投研看板: %s", title)
    build_dashboard(title, md_content)


def send_email(title, md_content):
    build_dashboard(title, md_content)


if __name__ == "__main__":
    build_dashboard("系统状态同步", "已完成最新数据构建。")
