import os
import json
from datetime import datetime, timezone, timedelta
from config import (
    FEISHU_APP_ID, FEISHU_URL, LLM_API_KEYS,
    COINGECKO_API_KEY, TAVILY_API_KEY
)
from feishu_db import FeishuDB

LOCAL_DB_PATH = "docs/alpha_db.json"


def load_local_db():
    if os.path.exists(LOCAL_DB_PATH):
        try:
            with open(LOCAL_DB_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ 读取本地数据库失败: {e}")
    return {
        "updated_at": "",
        "hot_keywords": [],
        "vc_And_news": [],
        "tracks": [],
        "projects": []
    }


def save_local_db(data):
    os.makedirs("docs", exist_ok=True)
    tz_bj = timezone(timedelta(hours=8))
    data["updated_at"] = datetime.now(tz_bj).strftime("%Y-%m-%d %H:%M:%S (UTC+8)")
    with open(LOCAL_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _get_str(fields, keys, default=""):
    for k in keys:
        val = fields.get(k)
        if val is not None and val != "":
            if isinstance(val, list):
                return ", ".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in val)
            return str(val)
    return default


def _get_float(fields, keys, default=0.0):
    for k in keys:
        val = fields.get(k)
        if val is not None and val != "":
            try:
                return float(str(val).replace("%", "").replace(",", "").strip())
            except Exception:
                continue
    return default


def build_dashboard(latest_alert_title="", latest_alert_md=""):
    print("🌐 正在构建 GitHub Pages 投研看板 V5.0 (docs/index.html)...")
    local_data = load_local_db()
    feishu_ok = False

    if FEISHU_APP_ID:
        try:
            db = FeishuDB()
            if db.token:
                feishu_ok = True
        except Exception as e:
            print(f"⚠️ 飞书状态检查异常: {e}")

    tz_bj = timezone(timedelta(hours=8))
    now_str = local_data.get("updated_at") or datetime.now(tz_bj).strftime("%Y-%m-%d %H:%M:%S (UTC+8)")
    hot_keywords = local_data.get("hot_keywords", [])
    vc_and_news = local_data.get("vc_And_news", [])
    tracks_data = local_data.get("tracks", [])
    projects_data = local_data.get("projects", [])

    api_status = [
        {"name": "智谱 GLM-4.7", "ok": bool(LLM_API_KEYS.get("glm")), "desc": "主脑投研引擎"},
        {"name": "Groq 极速引擎", "ok": bool(LLM_API_KEYS.get("groq")), "desc": "容灾备用大模型"},
        {"name": "飞书多维表格", "ok": feishu_ok, "desc": "云端数据库已连接" if feishu_ok else "本地 JSON 引擎驱动"},
        {"name": "GeckoTerminal/DEX", "ok": True, "desc": "链上实时金狗雷达"},
        {"name": "Tavily 深度背调", "ok": bool(TAVILY_API_KEY), "desc": "全网催化剂与VC背调"},
    ]

    status_html = ""
    for st in api_status:
        dot_color = "bg-emerald-400 shadow-[0_0_8px_#34d399]" if st["ok"] else "bg-amber-400 shadow-[0_0_8px_#fbbf24]"
        border_color = "border-emerald-500/20" if st["ok"] else "border-amber-500/20"
        status_html += f"""
        <div class="glass rounded-xl p-3.5 border {border_color} flex items-center justify-between">
            <div>
                <div class="text-xs text-slate-400">{st['desc']}</div>
                <div class="text-sm font-semibold text-white mt-0.5">{st['name']}</div>
            </div>
            <span class="w-3 h-3 rounded-full {dot_color}"></span>
        </div>
        """

    kw_html = ""
    if hot_keywords:
        for kw in hot_keywords:
            tag = kw.get("keyword", "")
            reason = kw.get("reason", "")
            heat = kw.get("heat", 85)
            kw_html += f"""
            <div class="bg-slate-900/90 border border-indigo-500/30 rounded-xl px-3.5 py-2.5 flex items-center gap-3 hover:border-indigo-400 transition">
                <span class="px-2 py-0.5 rounded-md text-xs font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">🔥 {heat}°</span>
                <div>
                    <div class="text-sm font-bold text-white">{tag}</div>
                    <div class="text-xs text-slate-400">{reason}</div>
                </div>
            </div>
            """
    else:
        kw_html = '<div class="text-slate-400 text-sm">正在等待热点叙事扫描...</div>'

    news_html = ""
    if vc_and_news:
        for item in vc_and_news[:8]:
            t_type = item.get("type", "情报")
            badge_cls = "bg-purple-500/20 text-purple-300 border-purple-500/30" if "VC" in t_type or "融资" in t_type else "bg-sky-500/20 text-sky-300 border-sky-500/30"
            news_html += f"""
            <div class="flex items-start gap-2.5 py-2 border-b border-slate-800/70 last:border-0 text-xs">
                <span class="px-2 py-0.5 rounded border {badge_cls} shrink-0 font-semibold">{t_type}</span>
                <span class="text-slate-300 leading-relaxed">{item.get('title', '')}</span>
            </div>
            """
    else:
        news_html = '<div class="text-slate-500 text-xs">暂无最新一级市场投融资与媒体快讯</div>'

    tracks_html = ""
    if tracks_data:
        for t in tracks_data[:8]:
            chg = float(t.get("change_24h", 0))
            chg_color = "text-emerald-400" if chg >= 0 else "text-rose-400"
            chg_sign = "+" if chg >= 0 else ""
            status = str(t.get("status", "已批准"))
            badge_bg = "bg-emerald-500/15 text-emerald-300 border-emerald-500/30" if "批准" in status else "bg-indigo-500/15 text-indigo-300 border-indigo-500/30"
            tracks_html += f"""
            <div class="glass rounded-xl p-4 border border-slate-800 hover:border-indigo-500/40 transition flex flex-col justify-between">
                <div>
                    <div class="flex items-center justify-between gap-2 mb-2">
                        <span class="text-xs px-2 py-0.5 rounded-full border {badge_bg}">{status}</span>
                        <span class="text-sm font-bold {chg_color}">{chg_sign}{chg:.2f}% (24h)</span>
                    </div>
                    <h3 class="text-base font-bold text-white mb-1">{t.get('name', '')}</h3>
                    <p class="text-xs text-slate-400 mb-3">来源: {t.get('source', '多维雷达')}</p>
                </div>
                <div class="text-xs text-slate-300 bg-slate-900/80 rounded-lg p-2.5 border border-slate-800/80 leading-relaxed">
                    💡 {t.get('reason', '具备较强叙事催化与资金关注度')}
                </div>
            </div>
            """

    projects_html = ""
    if projects_data:
        for p in projects_data:
            score = float(p.get("final_score", 0))
            score_badge = "from-emerald-500 to-teal-600" if score >= 78 else "from-indigo-500 to-purple-600"

            opp_type = p.get("opp_type", "🚀 叙事异动黑马")
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

            chain = (p.get("chain") or "MULTI").upper()
            contract_addr = p.get("contract_address") or ""
            short_addr = f"{contract_addr[:6]}...{contract_addr[-4:]}" if len(contract_addr) > 12 else ""

            chg_1h = float(p.get("change_1h", 0))
            chg_24h = float(p.get("change_24h", 0))
            chg_7d = float(p.get("change_7d", 0))
            c1h_cls = "text-emerald-400" if chg_1h >= 0 else "text-rose-400"
            c24_cls = "text-emerald-400" if chg_24h >= 0 else "text-rose-400"
            c7d_cls = "text-emerald-400" if chg_7d >= 0 else "text-rose-400"

            price_val = float(p.get("price", 0))
            price_str = f"${price_val:.6f}" if price_val < 0.01 else f"${price_val:.4f}"

            liq_wan = float(p.get("liquidity_wan", 0))
            buys_24h = int(p.get("buys_24h", 0))
            sells_24h = int(p.get("sells_24h", 0))
            buy_ratio = float(p.get("buy_ratio", 50.0))
            commits_4w = int(p.get("commits_4w", 0))
            vc_hits = p.get("vc_hits") or []

            # 根据项目类型展示差异化核心指标（Meme看池子流动性与买卖盘，价值项目看流通率与代码/VC）
            if filter_tag == "meme" or (buys_24h + sells_24h > 0):
                extra_metric_1_label = "DEX 池子流动性"
                extra_metric_1_val = f"${liq_wan:.1f}万" if liq_wan > 0 else "链上深度充足"
                extra_metric_2_label = "24h 链上买卖单"
                extra_metric_2_val = f"<span class='text-emerald-400'>{buys_24h}买</span> / <span class='text-rose-400'>{sells_24h}卖</span> ({buy_ratio}%)" if (buys_24h + sells_24h) > 0 else f"买盘占比 {buy_ratio}%"
            else:
                extra_metric_1_label = "MC/FDV 流通率"
                extra_metric_1_val = f"{p.get('mc_fdv_ratio', 0):.1f}%"
                extra_metric_2_label = "基本面/机构背调"
                extra_metric_2_val = f"VC: {', '.join(vc_hits[:2])}" if vc_hits else (f"GitHub月提交: {commits_4w}次" if commits_4w > 0 else f"距ATH: {p.get('ath_drop', 0):.1f}%")

            catalyst_str = p.get("catalyst") or "链上资金与叙事共振异动"
            report_html = str(p.get("ai_report", "")).replace("\n", "<br>")
            symbol_clean = str(p.get("symbol", "")).upper()
            dex_url = p.get("dex_url") or f"https://dexscreener.com/search?q={symbol_clean}"
            cg_id = p.get("coingecko_id") or p.get("id") or ""
            cg_url = f"https://www.coingecko.com/en/coins/{cg_id}" if cg_id and not str(cg_id).startswith("dex_") else f"https://www.coingecko.com/en/search?query={symbol_clean}"

            addr_badge = f'<span class="text-[11px] font-mono text-slate-400 bg-slate-800/90 px-2 py-0.5 rounded border border-slate-700" title="{contract_addr}">📋 {short_addr}</span>' if short_addr else ""

            projects_html += f"""
            <div class="project-card glass rounded-2xl p-5 border border-slate-800 hover:border-indigo-500/50 transition flex flex-col justify-between" data-type="{filter_tag}">
                <div>
                    <div class="flex items-start justify-between gap-2 mb-2.5">
                        <div>
                            <div class="flex items-center gap-2 flex-wrap">
                                <span class="text-xl font-extrabold text-white tracking-tight">${symbol_clean}</span>
                                <span class="text-xs px-2 py-0.5 rounded font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">{chain}</span>
                                <span class="text-xs px-2.5 py-0.5 rounded-full border font-semibold {type_cls}">{opp_type}</span>
                                {addr_badge}
                            </div>
                            <div class="flex items-center gap-2 mt-1.5 text-xs">
                                <span class="text-indigo-400 font-medium">🎯 细分赛道: {p.get('track', '早期Alpha')}</span>
                                <span class="text-slate-500">|</span>
                                <span class="text-slate-400">{p.get('name', '')}</span>
                            </div>
                        </div>
                        <div class="bg-gradient-to-r {score_badge} text-white text-xs font-bold px-3 py-1.5 rounded-xl shadow-lg shrink-0">
                            {score:.1f} 分
                        </div>
                    </div>

                    <div class="bg-amber-500/10 border border-amber-500/25 rounded-xl px-3 py-2 mb-3 text-xs text-amber-200 flex items-center gap-2">
                        <span class="shrink-0">⚡</span>
                        <span class="font-medium leading-snug">{catalyst_str}</span>
                    </div>

                    <div class="grid grid-cols-3 gap-2 my-3 bg-slate-900/90 p-3 rounded-xl border border-slate-800/90 text-xs">
                        <div>
                            <span class="text-slate-400 block">当前价格</span>
                            <span class="text-white font-bold text-sm">{price_str}</span>
                        </div>
                        <div>
                            <span class="text-slate-400 block">1h / 24h 动量</span>
                            <span class="font-bold text-sm"><span class="{c1h_cls}">{chg_1h:+.1f}%</span> / <span class="{c24_cls}">{chg_24h:+.1f}%</span></span>
                        </div>
                        <div>
                            <span class="text-slate-400 block">24h 换手率</span>
                            <span class="text-amber-300 font-semibold text-sm">{p.get('turnover_24h', 0):.1f}%</span>
                        </div>
                        <div>
                            <span class="text-slate-400 block">流通市值</span>
                            <span class="text-emerald-300 font-semibold">${p.get('market_cap', 0):.1f}万</span>
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
                    <span>⏱️ 背调时间: {p.get('discovered_at', now_str[:16])}</span>
                    <div class="flex items-center gap-2">
                        <a href="{dex_url}" target="_blank" class="px-2.5 py-1 rounded-lg bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 border border-emerald-500/30 transition font-medium">DexScreener ↗</a>
                        <a href="https://x.com/search?q=%24{symbol_clean}&src=typed_query&f=live" target="_blank" class="px-2.5 py-1 rounded-lg bg-sky-500/10 text-sky-300 hover:bg-sky-500/20 border border-sky-500/30 transition font-medium">𝕏 社区舆情 ↗</a>
                        <a href="{cg_url}" target="_blank" class="px-2.5 py-1 rounded-lg bg-indigo-500/10 text-indigo-300 hover:bg-indigo-500/20 border border-indigo-500/30 transition font-medium">CoinGecko ↗</a>
                    </div>
                </div>
            </div>
            """
    else:
        projects_html = """
        <div class="col-span-2 glass rounded-2xl p-8 text-center text-slate-400">
            正在执行早期 Alpha 与链上金狗深度背调，请稍后刷新页面...
        </div>
        """

    feishu_btn = (
        f'<a href="{FEISHU_URL}" target="_blank" class="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition shadow-lg shadow-indigo-600/30">📊 打开飞书控制台</a>'
        if FEISHU_URL else ""
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Crypto Alpha Hunter V5.0 | 早期高赔率项目与链上金狗狙击系统</title>
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
                        <span class="text-xs px-2 py-0.5 rounded-md bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-semibold">V5.0 早期狙击版</span>
                    </div>
                    <p class="text-xs text-slate-400">剔除大市值老白马 · GeckoTerminal/DexScreener 链上金狗雷达 · 强制深度背调验真</p>
                </div>
            </div>
            <div class="flex items-center gap-3">
                <span class="text-xs text-slate-400 bg-slate-900 px-3 py-1.5 rounded-lg border border-slate-800">🕒 最新扫描: {now_str}</span>
                {feishu_btn}
            </div>
        </div>
    </header>

    <main class="max-w-7xl mx-auto px-4 mt-6 space-y-8">
        <section>
            <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                {status_html}
            </div>
        </section>

        <section class="grid grid-cols-1 lg:grid-cols-3 gap-5">
            <div class="lg:col-span-2 glass rounded-2xl p-5 border border-slate-800">
                <div class="flex items-center justify-between mb-3">
                    <h2 class="text-base font-bold text-white flex items-center gap-2">🔥 全网热点叙事关键词云 (AI 提炼)</h2>
                    <span class="text-xs text-slate-400">CoinGecko 热搜 + 链上热池 + 媒体共振</span>
                </div>
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {kw_html}
                </div>
            </div>
            <div class="glass rounded-2xl p-5 border border-slate-800">
                <div class="flex items-center justify-between mb-3">
                    <h2 class="text-base font-bold text-white">📰 一级市场融资与快讯</h2>
                    <span class="text-xs text-slate-400">DeFiLlama VC / RSS</span>
                </div>
                <div class="max-h-48 overflow-y-auto pr-1">
                    {news_html}
                </div>
            </div>
        </section>

        <section>
            <div class="flex items-center justify-between mb-4">
                <div>
                    <h2 class="text-lg font-bold text-white">🎯 早期高赔率 Alpha 标的池（已完成深度背调验真）</h2>
                    <p class="text-xs text-slate-400">已自动排除 Top 大市值老白马，聚焦 $20万 ~ $3亿 市值区间的早期高弹性标的</p>
                </div>
                <div class="flex flex-wrap gap-2">
                    <button onclick="filterProjects('all')" class="filter-btn active px-3 py-1.5 rounded-xl text-xs font-bold bg-indigo-600 text-white transition">全部精选 ({len(projects_data)})</button>
                    <button onclick="filterProjects('meme')" class="filter-btn px-3 py-1.5 rounded-xl text-xs font-bold bg-slate-800 text-amber-300 hover:bg-slate-700 transition">🐶 链上早期Meme/金狗</button>
                    <button onclick="filterProjects('breakout')" class="filter-btn px-3 py-1.5 rounded-xl text-xs font-bold bg-slate-800 text-purple-300 hover:bg-slate-700 transition">🚀 叙事异动黑马</button>
                    <button onclick="filterProjects('leader')" class="filter-btn px-3 py-1.5 rounded-xl text-xs font-bold bg-slate-800 text-emerald-300 hover:bg-slate-700 transition">📈 强势赛道龙头</button>
                    <button onclick="filterProjects('value')" class="filter-btn px-3 py-1.5 rounded-xl text-xs font-bold bg-slate-800 text-sky-300 hover:bg-slate-700 transition">💎 机构潜伏/底部价值</button>
                </div>
            </div>
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-5">
                {projects_html}
            </div>
        </section>

        <section>
            <div class="flex items-center justify-between mb-3">
                <h2 class="text-lg font-bold text-white">📡 重点监控叙事赛道雷达</h2>
                <span class="text-xs text-slate-400">已过滤稳定币与包装资产噪音</span>
            </div>
            <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                {tracks_html}
            </div>
        </section>
    </main>

    <script>
        function filterProjects(type) {{
            const cards = document.querySelectorAll('.project-card');
            const btns = document.querySelectorAll('.filter-btn');
            btns.forEach(b => {{
                b.classList.remove('bg-indigo-600', 'text-white');
                b.classList.add('bg-slate-800');
            }});
            event.currentTarget.classList.remove('bg-slate-800');
            event.currentTarget.classList.add('bg-indigo-600', 'text-white');

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
    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("✅ Web 投研看板 V5.0 已生成: docs/index.html")


def send_wechat(title, md_content):
    print(f"📣 更新投研看板: {title}")
    build_dashboard(title, md_content)


def send_email(title, md_content):
    build_dashboard(title, md_content)


if __name__ == "__main__":
    build_dashboard("系统状态同步", "已完成最新数据构建。")
