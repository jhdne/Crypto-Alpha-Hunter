# notifier.py - V7.0 GitHub Pages 投研看板（趋势配置清单 · 多维交叉验证 · 盈亏比进化中枢）
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
                normalized.append({"type": "🔥 热搜飙升", "title": item})
            elif "融资" in item or "VC" in item:
                normalized.append({"type": "💰 VC融资", "title": item})
            elif "TVL" in item:
                normalized.append({"type": "🌊 TVL异动", "title": item})
            else:
                normalized.append({"type": "📰 媒体快讯", "title": item})
    return normalized


def build_dashboard(latest_alert_title="", latest_alert_md=""):
    log.info("正在构建 GitHub Pages 投研看板 V7.0 (docs/index.html)...")
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
    now_str = local_data.get("updated_at") or datetime.now(tz_bj).strftime("%Y-%m-%d %H:%M:%S (UTC+8)")
    evo = local_data.get("evolution_state") or DEFAULT_EVOLUTION_STATE
    guardrails = evo.get("guardrails") or DEFAULT_EVOLUTION_STATE["guardrails"]
    tactical_rules = evo.get("tactical_rules") or DEFAULT_EVOLUTION_STATE["tactical_rules"]

    hot_keywords = local_data.get("hot_keywords") or local_data.get("keywords") or []
    vc_and_news = _normalize_news_items(local_data)
    tracks_data = local_data.get("tracks", [])
    allocation_matrix = local_data.get("allocation_matrix", [])
    projects_data = [normalize_project(p) for p in (local_data.get("projects") or [])]

    alert_payload = local_data.get("alert") or {}
    if latest_alert_title or latest_alert_md:
        alert_payload = {
            "title": latest_alert_title or alert_payload.get("title", "系统状态同步"),
            "content": latest_alert_md or alert_payload.get("content", ""),
            "time": now_str,
            "projects_count": len(projects_data),
        }
    os.makedirs("docs", exist_ok=True)
    with open(LATEST_ALERT_PATH, "w", encoding="utf-8") as f:
        json.dump(alert_payload, f, ensure_ascii=False, indent=2)

    api_status = [
        {"name": "智谱 GLM 引擎", "ok": bool(LLM_API_KEYS.get("glm")), "desc": "多空并行辩论投委会"},
        {"name": "Groq 极速引擎", "ok": bool(LLM_API_KEYS.get("groq")), "desc": "容灾备用大模型"},
        {"name": "类脑进化中枢", "ok": True, "desc": f"Gen #{int(evo.get('generation', 1))} · 盈亏比 {float(evo.get('payoff_ratio', 1.0)):.2f}"},
        {"name": "多维交叉验证", "ok": True, "desc": "链上+TVL+VC+合约审计"},
        {"name": "飞书/本地双擎", "ok": True, "desc": "云端已连接" if feishu_ok else "本地 JSON 实时闭环"},
    ]

    status_html = ""
    for st in api_status:
        dot_color = (
            "bg-emerald-400 shadow-[0_0_8px_#34d399]"
            if st["ok"]
            else "bg-amber-400 shadow-[0_0_8px_#fbbf24]"
        )
        border_color = "border-emerald-500/20" if st["ok"] else "border-amber-500/20"
        status_html += f"""
        <div class="glass rounded-xl p-3.5 border {border_color} flex items-center justify-between">
            <div>
                <div class="text-xs text-slate-400">{_esc(st['desc'])}</div>
                <div class="text-sm font-semibold text-white mt-0.5">{_esc(st['name'])}</div>
            </div>
            <span class="w-3 h-3 rounded-full {dot_color}"></span>
        </div>
        """

    avg_roi = float(evo.get("avg_roi_pct", 0.0))
    roi_cls = "text-emerald-400" if avg_roi >= 0 else "text-rose-400"
    payoff_ratio = float(evo.get("payoff_ratio", 1.0))
    expectancy_pct = float(evo.get("expectancy_pct", 0.0))
    rules_html = "".join([
        f'<li class="text-xs text-slate-300 flex items-start gap-2"><span class="text-emerald-400 shrink-0">✔</span><span>{_esc(r)}</span></li>'
        for r in tactical_rules[:3]
    ])

    evolution_html = f"""
    <section class="glass rounded-2xl p-5 border border-emerald-500/30 bg-gradient-to-r from-slate-900/95 via-indigo-950/30 to-slate-900/95">
        <div class="flex flex-wrap items-center justify-between gap-3 mb-4 border-b border-slate-800/80 pb-3">
            <div class="flex items-center gap-2.5">
                <span class="px-2.5 py-1 rounded-lg text-xs font-extrabold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">🧬 Gen #{int(evo.get('generation', 1))} 类脑进化中枢</span>
                <h2 class="text-base font-bold text-white">胜率 × 盈亏比策略归因与动态风控引擎</h2>
            </div>
            <span class="text-xs text-slate-400">最近进化: {_esc(evo.get('last_evolved_at', now_str[:16]))}</span>
        </div>

        <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-4">
            <div class="bg-slate-900/90 rounded-xl p-3 border border-slate-800">
                <div class="text-xs text-slate-400">实盘正收益胜率</div>
                <div class="text-base font-extrabold text-emerald-400 mt-0.5">{float(evo.get('win_rate_pct', 0)):.1f}% <span class="text-[11px] text-slate-500 font-normal">({int(evo.get('total_tested', 0))}样本)</span></div>
            </div>
            <div class="bg-slate-900/90 rounded-xl p-3 border border-slate-800">
                <div class="text-xs text-slate-400">均益 / 单笔期望</div>
                <div class="text-base font-extrabold {roi_cls} mt-0.5">{avg_roi:+.1f}% <span class="text-[11px] text-slate-400 font-normal">({expectancy_pct:+.1f}%)</span></div>
            </div>
            <div class="bg-slate-900/90 rounded-xl p-3 border border-emerald-500/30">
                <div class="text-xs text-slate-400">策略盈亏比 (Payoff)</div>
                <div class="text-base font-extrabold text-amber-300 mt-0.5">{payoff_ratio:.2f} : 1</div>
            </div>
            <div class="bg-slate-900/90 rounded-xl p-3 border border-indigo-500/30">
                <div class="text-xs text-slate-400">24h 防追高红线</div>
                <div class="text-base font-extrabold text-rose-300 mt-0.5">+{float(guardrails.get('max_24h_pump_limit', 68)):.0f}%</div>
            </div>
            <div class="bg-slate-900/90 rounded-xl p-3 border border-indigo-500/30">
                <div class="text-xs text-slate-400">Meme / 叙事市值上限</div>
                <div class="text-sm font-extrabold text-sky-300 mt-0.5">${float(guardrails.get('max_meme_mc_wan', 1500)):.0f}万 / ${float(guardrails.get('max_narrative_mc_wan', 5000)):.0f}万</div>
            </div>
            <div class="bg-slate-900/90 rounded-xl p-3 border border-indigo-500/30">
                <div class="text-xs text-slate-400">近期最佳捕获</div>
                <div class="text-sm font-bold text-amber-300 mt-0.5 truncate">{_esc(evo.get('best_pick', '暂无'))}</div>
            </div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 bg-slate-950/70 rounded-xl p-3.5 border border-slate-800/80">
            <div>
                <div class="text-xs font-bold text-indigo-300 mb-1.5">🧠 本轮策略归因与自我反思：</div>
                <p class="text-xs text-slate-300 leading-relaxed">{_esc(evo.get('evolution_reason', ''))}</p>
                <p class="text-[11px] text-slate-400 mt-1.5">📊 分层归因：{_esc(evo.get('attribution_summary', '积累中'))}</p>
            </div>
            <div>
                <div class="text-xs font-bold text-emerald-300 mb-1.5">⚖️ 已注入投委会的强制狙击铁律：</div>
                <ul class="space-y-1">{rules_html}</ul>
            </div>
        </div>
    </section>
    """

    alloc_html = ""
    if allocation_matrix:
        for item in allocation_matrix[:4]:
            alloc_html += f"""
            <div class="glass rounded-xl p-4 border border-indigo-500/25 flex flex-col justify-between">
                <div>
                    <div class="flex items-center justify-between gap-2 mb-2">
                        <span class="text-sm font-bold text-white">{_esc(item.get('track', ''))}</span>
                        <span class="text-[11px] px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">{_esc(item.get('ratio_hint', '龙头50% / 黑马50%'))}</span>
                    </div>
                    <p class="text-xs text-slate-400 mb-2.5 leading-relaxed">{_esc(item.get('trend_thesis', ''))}</p>
                </div>
                <div class="space-y-1.5 text-xs bg-slate-900/90 p-2.5 rounded-lg border border-slate-800">
                    <div class="text-emerald-300"><span class="font-semibold">🏛️ 龙头配置：</span>{_esc(item.get('leader', ''))}</div>
                    <div class="text-amber-300"><span class="font-semibold">🐎 黑马弹性：</span>{_esc(item.get('dark_horse', ''))}</div>
                </div>
            </div>
            """
    else:
        alloc_html = '<div class="col-span-4 text-xs text-slate-400">运行趋势推演任务后将自动生成各赛道龙头与黑马配置清单...</div>'

    kw_html = ""
    if hot_keywords:
        for kw in hot_keywords:
            tag = kw.get("keyword") or kw.get("word") or ""
            reason = kw.get("reason", "")
            heat = int(kw.get("heat", 85) or 85)
            kw_html += f"""
            <div class="bg-slate-900/90 border border-indigo-500/30 rounded-xl px-3.5 py-2.5 flex items-center gap-3 hover:border-indigo-400 transition">
                <span class="px-2 py-0.5 rounded-md text-xs font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">🔥 {heat}°</span>
                <div>
                    <div class="text-sm font-bold text-white">{_esc(tag)}</div>
                    <div class="text-xs text-slate-400">{_esc(reason)}</div>
                </div>
            </div>
            """
    else:
        kw_html = '<div class="text-slate-400 text-sm">正在等待热点叙事扫描...</div>'

    news_html = ""
    if vc_and_news:
        for item in vc_and_news[:8]:
            t_type = item.get("type", "情报")
            badge_cls = (
                "bg-purple-500/20 text-purple-300 border-purple-500/30"
                if ("VC" in t_type or "融资" in t_type or "TVL" in t_type)
                else "bg-sky-500/20 text-sky-300 border-sky-500/30"
            )
            news_html += f"""
            <div class="flex items-start gap-2.5 py-2 border-b border-slate-800/70 last:border-0 text-xs">
                <span class="px-2 py-0.5 rounded border {badge_cls} shrink-0 font-semibold">{_esc(t_type)}</span>
                <span class="text-slate-300 leading-relaxed">{_esc(item.get('title', ''))}</span>
            </div>
            """
    else:
        news_html = '<div class="text-slate-500 text-xs">暂无最新一级市场投融资与媒体快讯</div>'

    tracks_html = ""
    if tracks_data:
        for t in tracks_data[:8]:
            t_name = t.get("name") or t.get("赛道名称") or ""
            t_source = t.get("source") or t.get("发现来源") or "多维雷达"
            t_reason = t.get("reason") or t.get("AI赛道简评") or "具备较强叙事催化与资金关注度"
            chg = float(t.get("change_24h") if t.get("change_24h") is not None else (t.get("24h涨幅(%)") or 0))
            chg_color = "text-emerald-400" if chg >= 0 else "text-rose-400"
            chg_sign = "+" if chg >= 0 else ""
            status = str(t.get("status") or t.get("人工状态") or "已批准")
            badge_bg = (
                "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
                if ("批准" in status or "允许" in status)
                else "bg-indigo-500/15 text-indigo-300 border-indigo-500/30"
            )
            tracks_html += f"""
            <div class="glass rounded-xl p-4 border border-slate-800 hover:border-indigo-500/40 transition flex flex-col justify-between">
                <div>
                    <div class="flex items-center justify-between gap-2 mb-2">
                        <span class="text-xs px-2 py-0.5 rounded-full border {badge_bg}">{_esc(status)}</span>
                        <span class="text-sm font-bold {chg_color}">{chg_sign}{chg:.2f}% (24h)</span>
                    </div>
                    <h3 class="text-base font-bold text-white mb-1">{_esc(t_name)}</h3>
                    <p class="text-xs text-slate-400 mb-3">来源: {_esc(t_source)}</p>
                </div>
                <div class="text-xs text-slate-300 bg-slate-900/80 rounded-lg p-2.5 border border-slate-800/80 leading-relaxed">
                    💡 {_esc(t_reason)}
                </div>
            </div>
            """

    projects_html = ""
    if projects_data:
        for p in projects_data:
            score = p["score"]
            score_badge = "from-emerald-500 to-teal-600" if score >= 78 else "from-indigo-500 to-purple-600"

            opp_type = p["project_type"]
            if "Meme" in opp_type or "金狗" in opp_type:
                type_cls = "bg-amber-500/20 text-amber-300 border-amber-500/40"
                filter_tag = "meme"
            elif "龙头" in opp_type:
                type_cls = "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
                filter_tag = "leader"
            elif "异动" in opp_type or "黑马" in opp_type:
                type_cls = "bg-purple-500/20 text-purple-300 border-purple-500/40"
                filter_tag = "breakout"
            else:
                type_cls = "bg-sky-500/20 text-sky-300 border-sky-500/40"
                filter_tag = "value"

            chain = p["chain"].upper()
            contract_addr = p["contract"]
            short_addr = f"{contract_addr[:6]}...{contract_addr[-4:]}" if len(contract_addr) > 12 else contract_addr

            chg_1h = p["chg_1h"]
            chg_24h = p["chg_24h"]
            c1h_cls = "text-emerald-400" if chg_1h >= 0 else "text-rose-400"
            c24_cls = "text-emerald-400" if chg_24h >= 0 else "text-rose-400"

            price_val = p["price"]
            price_str = f"${price_val:.6f}" if price_val < 0.01 else f"${price_val:.4f}"

            live_roi = p["live_roi_pct"]
            roi_cls_badge = (
                "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
                if live_roi >= 0
                else "bg-rose-500/20 text-rose-300 border-rose-500/40"
            )
            roi_badge = (
                f'<span class="text-xs px-2 py-0.5 rounded {roi_cls_badge} border font-bold">实盘 {live_roi:+.1f}%</span>'
                if live_roi != 0
                else ""
            )

            liq_wan = p["liq_wan"]
            buys_24h = p["buys_24h"]
            sells_24h = p["sells_24h"]
            buy_ratio = p["buy_ratio"]
            commits_4w = p["commits_4w"]
            vc_hits = p["vc_hits"]

            if filter_tag == "meme" or (buys_24h + sells_24h > 0):
                extra_metric_1_label = "DEX 池子流动性"
                extra_metric_1_val = f"${liq_wan:.1f}万" if liq_wan > 0 else "链上深度充足"
                extra_metric_2_label = "24h 链上买卖单"
                extra_metric_2_val = (
                    f"<span class='text-emerald-400'>{buys_24h}买</span> / <span class='text-rose-400'>{sells_24h}卖</span> ({buy_ratio:.1f}%)"
                    if (buys_24h + sells_24h) > 0
                    else f"买盘占比 {buy_ratio:.1f}%"
                )
            else:
                extra_metric_1_label = "MC/FDV 流通率"
                extra_metric_1_val = f"{p['mc_fdv_ratio']:.1f}%"
                extra_metric_2_label = "基本面/机构背调"
                extra_metric_2_val = (
                    _esc(f"VC: {', '.join(str(v) for v in vc_hits[:2])}")
                    if vc_hits
                    else (
                        f"GitHub月提交: {commits_4w}次"
                        if commits_4w > 0
                        else f"距ATH: {p['ath_drop']:.1f}%"
                    )
                )

            catalyst_str = p["catalyst"] or "处于极早期放量启动窗口，买盘主动吸筹"
            report_html = _esc(p["report"]).replace("\n", "<br>")
            symbol_clean = p["symbol"]
            dex_url = _safe_url(p["dex_url"], f"https://dexscreener.com/search?q={_esc(symbol_clean)}")
            cg_id = p.get("coingecko_id") or p.get("id") or ""
            cg_url = _safe_url(
                f"https://www.coingecko.com/en/coins/{cg_id}"
                if cg_id and not str(cg_id).startswith("dex_")
                else f"https://www.coingecko.com/en/search?query={symbol_clean}"
            )
            x_url = _safe_url(f"https://x.com/search?q=%24{symbol_clean}&src=typed_query&f=live")

            addr_badge = (
                f'<span class="text-[11px] font-mono text-slate-400 bg-slate-800/90 px-2 py-0.5 rounded border border-slate-700" title="{_esc(contract_addr)}">📋 {_esc(short_addr)}</span>'
                if short_addr
                else ""
            )

            projects_html += f"""
            <div class="project-card glass rounded-2xl p-5 border border-slate-800 hover:border-indigo-500/50 transition flex flex-col justify-between" data-type="{filter_tag}">
                <div>
                    <div class="flex items-start justify-between gap-2 mb-2.5">
                        <div>
                            <div class="flex items-center gap-2 flex-wrap">
                                <span class="text-xl font-extrabold text-white tracking-tight">${_esc(symbol_clean)}</span>
                                <span class="text-xs px-2 py-0.5 rounded font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">{_esc(chain)}</span>
                                <span class="text-xs px-2.5 py-0.5 rounded-full border font-semibold {type_cls}">{_esc(opp_type)}</span>
                                <span class="text-xs px-2 py-0.5 rounded-md bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 font-semibold">{_esc(p['entry_timing'])}</span>
                                <span class="text-xs px-2 py-0.5 rounded-md bg-sky-500/15 text-sky-300 border border-sky-500/30">{_esc(p['cv_confidence'])}</span>
                                {roi_badge}
                                {addr_badge}
                            </div>
                            <div class="flex items-center gap-2 mt-1.5 text-xs flex-wrap">
                                <span class="text-amber-300 font-semibold">{_esc(p['age_label'])}</span>
                                <span class="text-slate-600">|</span>
                                <span class="text-indigo-400 font-medium">🎯 {_esc(p['track'])}</span>
                                <span class="text-slate-600">|</span>
                                <span class="text-emerald-300 font-medium">💼 {_esc(p['position_tier'])}</span>
                                <span class="text-slate-600">|</span>
                                <span class="text-slate-400">{_esc(p['name'])}</span>
                            </div>
                        </div>
                        <div class="bg-gradient-to-r {score_badge} text-white text-xs font-bold px-3 py-1.5 rounded-xl shadow-lg shrink-0">
                            {score:.1f} 分
                        </div>
                    </div>

                    <div class="bg-amber-500/10 border border-amber-500/25 rounded-xl px-3 py-2 mb-3 text-xs text-amber-200 flex items-center gap-2">
                        <span class="shrink-0">⚡</span>
                        <span class="font-medium leading-snug">{_esc(catalyst_str)}</span>
                    </div>

                    <div class="grid grid-cols-3 gap-2 my-3 bg-slate-900/90 p-3 rounded-xl border border-slate-800/90 text-xs">
                        <div>
                            <span class="text-slate-400 block">建仓参考价</span>
                            <span class="text-white font-bold text-sm">{price_str}</span>
                        </div>
                        <div>
                            <span class="text-slate-400 block">1h 点火 / 24h 涨幅</span>
                            <span class="font-bold text-sm"><span class="{c1h_cls}">{chg_1h:+.1f}%</span> / <span class="{c24_cls}">{chg_24h:+.1f}%</span></span>
                        </div>
                        <div>
                            <span class="text-slate-400 block">24h 换手率</span>
                            <span class="text-amber-300 font-semibold text-sm">{p['turnover_24h']:.1f}%</span>
                        </div>
                        <div>
                            <span class="text-slate-400 block">早期流通市值</span>
                            <span class="text-emerald-300 font-semibold">${p['mc_wan']:.1f}万</span>
                        </div>
                        <div>
                            <span class="text-slate-400 block">{extra_metric_1_label}</span>
                            <span class="text-sky-300 font-semibold">{extra_metric_1_val}</span>
                        </div>
                        <div>
                            <span class="text-slate-400 block">{extra_metric_2_label}</span>
                            <span class="text-slate-200 font-semibold">{extra_metric_2_val}</span>
                        </div>
                    </div>

                    <div class="text-xs text-slate-300 bg-slate-950/80 rounded-xl p-3.5 border border-slate-800/80 leading-relaxed max-h-56 overflow-y-auto">
                        {report_html}
                    </div>
                </div>

                <div class="mt-4 pt-3 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-400">
                    <span>⏱️ 狙击时间: {_esc(p['found_at'] or now_str[:16])}</span>
                    <div class="flex items-center gap-2">
                        <a href="{dex_url}" target="_blank" rel="noopener noreferrer" class="px-2.5 py-1 rounded-lg bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 border border-emerald-500/30 transition font-medium">DexScreener ↗</a>
                        <a href="{x_url}" target="_blank" rel="noopener noreferrer" class="px-2.5 py-1 rounded-lg bg-sky-500/10 text-sky-300 hover:bg-sky-500/20 border border-sky-500/30 transition font-medium">𝕏 社区舆情 ↗</a>
                        <a href="{cg_url}" target="_blank" rel="noopener noreferrer" class="px-2.5 py-1 rounded-lg bg-indigo-500/10 text-indigo-300 hover:bg-indigo-500/20 border border-indigo-500/30 transition font-medium">CoinGecko ↗</a>
                    </div>
                </div>
            </div>
            """
    else:
        projects_html = """
        <div class="col-span-2 glass rounded-2xl p-8 text-center text-slate-400">
            正在执行极早期 Alpha 与链上新池金狗深度背调，请稍后刷新页面...
        </div>
        """

    feishu_btn = (
        f'<a href="{_safe_url(FEISHU_DASHBOARD_URL)}" target="_blank" rel="noopener noreferrer" class="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition shadow-lg shadow-indigo-600/30">📊 打开飞书控制台</a>'
        if FEISHU_DASHBOARD_URL
        else ""
    )

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Crypto Alpha Hunter V7.0 | 全周期 Alpha 捕获与类脑进化投研系统</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {{ background-color: #070b14; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        .glass {{ background: rgba(15, 23, 42, 0.78); backdrop-filter: blur(12px); }}
        ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
        ::-webkit-scrollbar-thumb {{ background: #334155; border-radius: 3px; }}
    </style>
</head>
<body class="min-h-screen pb-16">
    <header class="border-b border-slate-800/80 bg-slate-950/60 sticky top-0 z-50 backdrop-blur-md">
        <div class="max-w-7xl mx-auto px-4 py-4 flex flex-wrap items-center justify-between gap-4">
            <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 via-purple-600 to-emerald-500 flex items-center justify-center text-xl shadow-lg">🦅</div>
                <div>
                    <div class="flex items-center gap-2">
                        <h1 class="text-lg font-bold text-white">Crypto Alpha Hunter</h1>
                        <span class="text-xs px-2 py-0.5 rounded-md bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-semibold">V7.0 全周期·类脑进化版</span>
                    </div>
                    <p class="text-xs text-slate-400">多空并行辩论 · 多维交叉验证 · 胜率与盈亏比动态平衡 · 龙头/黑马前瞻配置</p>
                </div>
            </div>
            <div class="flex items-center gap-3">
                <span class="text-xs text-slate-400 bg-slate-900 px-3 py-1.5 rounded-lg border border-slate-800">🕒 最新扫描: {_esc(now_str)}</span>
                {feishu_btn}
            </div>
        </div>
    </header>

    <main class="max-w-7xl mx-auto px-4 mt-6 space-y-7">
        <section>
            <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                {status_html}
            </div>
        </section>

        {evolution_html}

        <section>
            <div class="flex items-center justify-between mb-3">
                <h2 class="text-lg font-bold text-white">🧭 趋势推演与前瞻配置清单（龙头确定性 × 黑马高弹性）</h2>
                <span class="text-xs text-slate-400">AI 宏观趋势推演输出</span>
            </div>
            <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                {alloc_html}
            </div>
        </section>

        <section class="grid grid-cols-1 lg:grid-cols-3 gap-5">
            <div class="lg:col-span-2 glass rounded-2xl p-5 border border-slate-800">
                <div class="flex items-center justify-between mb-3">
                    <h2 class="text-base font-bold text-white flex items-center gap-2">🔥 全网早期叙事关键词云 (AI 提炼)</h2>
                    <span class="text-xs text-slate-400">链上新池 + VC 融资 + TVL 异动 + 热搜共振</span>
                </div>
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {kw_html}
                </div>
            </div>
            <div class="glass rounded-2xl p-5 border border-slate-800">
                <div class="flex items-center justify-between mb-3">
                    <h2 class="text-base font-bold text-white">📰 一级市场融资与链上资金快讯</h2>
                    <span class="text-xs text-slate-400">DeFiLlama VC / TVL / RSS</span>
                </div>
                <div class="max-h-48 overflow-y-auto pr-1">
                    {news_html}
                </div>
            </div>
        </section>

        <section>
            <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
                <div>
                    <h2 class="text-lg font-bold text-white">🎯 全周期 Alpha 精选标的池（多维交叉验证 + 合约排雷通过）</h2>
                    <p class="text-xs text-slate-400">自动拦截 24h 暴涨超 +{float(guardrails.get('max_24h_pump_limit', 68)):.0f}% 的高位接盘标的与高危合约</p>
                </div>
                <div class="flex flex-wrap gap-2">
                    <button onclick="filterProjects('all', this)" class="filter-btn active px-3 py-1.5 rounded-xl text-xs font-bold bg-indigo-600 text-white transition">全部精选 ({len(projects_data)})</button>
                    <button onclick="filterProjects('meme', this)" class="filter-btn px-3 py-1.5 rounded-xl text-xs font-bold bg-slate-800 text-amber-300 hover:bg-slate-700 transition">🐶 链上早期Meme/金狗</button>
                    <button onclick="filterProjects('breakout', this)" class="filter-btn px-3 py-1.5 rounded-xl text-xs font-bold bg-slate-800 text-purple-300 hover:bg-slate-700 transition">🚀 叙事异动黑马</button>
                    <button onclick="filterProjects('leader', this)" class="filter-btn px-3 py-1.5 rounded-xl text-xs font-bold bg-slate-800 text-emerald-300 hover:bg-slate-700 transition">📈 强势赛道龙头</button>
                    <button onclick="filterProjects('value', this)" class="filter-btn px-3 py-1.5 rounded-xl text-xs font-bold bg-slate-800 text-sky-300 hover:bg-slate-700 transition">💎 机构潜伏/底部价值</button>
                </div>
            </div>
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-5">
                {projects_html}
            </div>
        </section>

        <section>
            <div class="flex items-center justify-between mb-3">
                <h2 class="text-lg font-bold text-white">📡 重点监控早期轮动赛道雷达</h2>
                <span class="text-xs text-slate-400">已过滤稳定币与包装资产噪音</span>
            </div>
            <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                {tracks_html}
            </div>
        </section>
    </main>

    <script>
        function filterProjects(type, btnEl) {{
            const cards = document.querySelectorAll('.project-card');
            const btns = document.querySelectorAll('.filter-btn');
            btns.forEach(b => {{
                b.classList.remove('bg-indigo-600', 'text-white');
                b.classList.add('bg-slate-800');
            }});
            if (btnEl) {{
                btnEl.classList.remove('bg-slate-800');
                btnEl.classList.add('bg-indigo-600', 'text-white');
            }}

            cards.forEach(card => {{
                if (type === 'all' || card.dataset.type === type) {{
                    card.style.display = 'flex';
                }} else {{
                    card.style.display = 'none';
                }}
            }});
        }}
    </script>
</body>
</html>
"""
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    log.info("Web 投研看板 V7.0 已生成: docs/index.html")


def send_wechat(title, md_content):
    log.info("更新投研看板: %s", title)
    build_dashboard(title, md_content)


def send_email(title, md_content):
    build_dashboard(title, md_content)


if __name__ == "__main__":
    build_dashboard("系统状态同步", "已完成最新数据构建。")
