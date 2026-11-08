# notifier.py - V4.0 机构级加密投研终端生成器
from datetime import datetime, timedelta, timezone
import json
import os
import config
import feishu_db

DB_FILE = "docs/alpha_db.json"


def _safe_float(val, default=0.0):
  try:
    return float(val) if val is not None and val != "" else default
  except Exception:
    return default


def send_wechat(title, md_content):
  build_dashboard()


def send_email(title, md_content):
  build_dashboard()


def build_dashboard():
  print("🌐 正在编译生成 V4.0 机构级 Web 投研终端 (docs/index.html)...")
  os.makedirs("docs", exist_ok=True)
  bj_now = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime(
      "%Y-%m-%d %H:%M:%S"
  )

  db = {
      "api_status": {},
      "keywords": [],
      "vc_news": [],
      "tracks": [],
      "projects": [],
      "alert": {},
  }
  if os.path.exists(DB_FILE):
    try:
      with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)
    except Exception:
      pass

  alert = db.get("alert") or {
      "title": "V4.0 双轮驱动猎手巡航中",
      "content": "实时监控全网 Meme 热搜异动与主流赛道反弹龙头...",
      "time": bj_now,
  }
  tracks = db.get("tracks", [])
  projects = sorted(
      db.get("projects", []),
      key=lambda x: _safe_float(x.get("综合总分"), 0),
      reverse=True,
  )

  # 1. 顶部五大 API 实时状态灯
  api_st = db.get("api_status", {})
  api_items = [
      ("coingecko", "二级行情与热搜引擎", "实时在线"),
      ("vc_media", "一级VC融资与媒体源", "实时在线"),
      ("llm", "AI 投委会 (GLM/Groq)", "多智能体在线"),
      ("tavily", "链上换手与动量雷达", "双轮驱动在线"),
      ("feishu", "飞书控制台 & 双保险库", "同步正常"),
  ]
  api_html = ""
  for k, label, def_msg in api_items:
    st = api_st.get(k, {"ok": True, "msg": def_msg})
    ok = st.get("ok", True)
    dot = (
        '<span class="inline-block w-2 h-2 rounded-full bg-emerald-400'
        ' animate-pulse"></span>'
        if ok
        else '<span class="inline-block w-2 h-2 rounded-full'
        ' bg-amber-400"></span>'
    )
    api_html += f"""
        <div class="bg-slate-900/90 border border-slate-800/90 rounded-xl p-3 flex flex-col justify-between">
            <div class="text-xs font-bold text-slate-200 flex items-center gap-2">{dot} {label}</div>
            <div class="text-[11px] text-emerald-400/90 mt-1 truncate font-mono">{st.get('msg', def_msg)}</div>
        </div>"""

  # 2. 宏观叙事热词与 VC 融资快讯
  kw_html = ""
  for kw in db.get("keywords", [])[:6]:
    kw_html += f"""
        <div class="bg-slate-950/80 border border-indigo-500/30 hover:border-indigo-400 rounded-xl p-3 transition flex justify-between items-center">
            <div>
                <div class="text-sm font-extrabold text-indigo-300">{kw.get('word', '')}</div>
                <div class="text-[11px] text-slate-400 mt-0.5">{kw.get('reason', '')}</div>
            </div>
            <div class="bg-indigo-500/20 border border-indigo-500/40 text-indigo-300 text-xs font-mono font-bold px-2.5 py-1 rounded-lg">🔥 {kw.get('heat', 92)}</div>
        </div>"""

  news_html = "".join([
      '<li class="text-xs text-slate-300 py-1.5 border-b border-slate-800/60'
      f' flex items-start gap-2"><span>•</span><span>{n}</span></li>'
      for n in db.get("vc_news", [])[:8]
  ])

  # 3. 热门反弹赛道卡片
  radar_html = ""
  for t in tracks[:8]:
    chg = _safe_float(t.get("24h涨幅(%)"), 0.0)
    chg_c = (
        "text-emerald-400 bg-emerald-500/10 border-emerald-500/30"
        if chg >= 0
        else "text-rose-400 bg-rose-500/10 border-rose-500/30"
    )
    radar_html += f"""
        <div class="bg-slate-900/90 border border-slate-800 hover:border-indigo-500/50 rounded-2xl p-4 transition flex flex-col justify-between">
            <div>
                <div class="flex justify-between items-start gap-2 mb-2">
                    <h3 class="font-extrabold text-white text-base leading-snug">{t.get('赛道名称', '')}</h3>
                    <span class="text-xs font-mono font-bold px-2 py-0.5 rounded border {chg_c}">{'+' if chg>=0 else ''}{chg:.1f}%</span>
                </div>
                <div class="flex items-center gap-2 mb-2.5">
                    <span class="text-[11px] bg-indigo-500/20 text-indigo-300 px-2 py-0.5 rounded font-medium">{t.get('发现来源', '🔥赛道反弹')}</span>
                    <span class="text-[11px] text-slate-500 font-mono truncate">{t.get('赛道ID', '')}</span>
                </div>
                <p class="text-xs text-slate-300 leading-relaxed">{t.get('AI赛道简评', '')}</p>
            </div>
        </div>"""

  # 4. 多智能体精选 Alpha 项目卡片（带分类筛选属性与直达K线按钮）
  alpha_html = ""
  for p in projects:
    score = _safe_float(p.get("综合总分"), 0.0)
    archetype = str(p.get("机会类型", "📈 赛道反弹龙头"))
    cat_tag = (
        "meme"
        if "Meme" in archetype or "异动" in archetype
        else ("rebound" if "反弹" in archetype else "value")
    )

    arch_badge = (
        "bg-rose-500/20 text-rose-300 border-rose-500/40"
        if cat_tag == "meme"
        else (
            "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
            if cat_tag == "rebound"
            else "bg-amber-500/20 text-amber-300 border-amber-500/40"
        )
    )
    score_cls = (
        "bg-gradient-to-r from-emerald-400 to-teal-500 text-slate-950"
        if score >= 82
        else "bg-indigo-600 text-white"
    )

    chg24 = _safe_float(p.get("24h涨跌(%)"), 0.0)
    chg24_c = "text-emerald-400" if chg24 >= 0 else "text-rose-400"
    chg7d = _safe_float(p.get("7d涨跌(%)"), 0.0)
    chg7d_c = "text-emerald-400" if chg7d >= 0 else "text-rose-400"

    sym_clean = str(p.get("代币符号", "")).replace("$", "")
    cg_url = f"https://www.coingecko.com/en/coins/{p.get('项目ID', '')}"
    dex_url = f"https://dexscreener.com/search?q={sym_clean}"
    report_html = str(p.get("多智能体投研报告", "")).replace("\n", "<br>")

    alpha_html += f"""
        <div class="project-card bg-slate-900/95 border border-slate-800 hover:border-indigo-500/60 rounded-2xl p-5 transition flex flex-col justify-between shadow-lg" data-category="{cat_tag}">
            <div>
                <div class="flex justify-between items-start gap-2 mb-3">
                    <div>
                        <div class="flex items-center gap-2 flex-wrap">
                            <span class="text-2xl font-black text-white tracking-tight">{p.get('代币符号', '')}</span>
                            <span class="text-xs text-slate-400 font-medium">{p.get('项目名称', '')}</span>
                            <span class="text-xs px-2.5 py-0.5 rounded-full border font-bold {arch_badge}">{archetype}</span>
                        </div>
                        <div class="text-xs text-indigo-400 mt-1 font-medium">所属叙事：{p.get('所属赛道', '')}</div>
                    </div>
                    <div class="px-3 py-1.5 rounded-xl font-mono font-black text-sm shadow {score_cls}">
                        {score} 分
                    </div>
                </div>

                <!-- 六维核心行情指标矩阵 -->
                <div class="grid grid-cols-3 sm:grid-cols-6 gap-2 bg-slate-950/90 p-3 rounded-xl border border-slate-800/80 mb-4 text-center">
                    <div>
                        <div class="text-[10px] text-slate-500">当前价格</div>
                        <div class="text-xs font-mono font-bold text-white mt-0.5">${p.get('推荐时价格', '-')}</div>
                    </div>
                    <div>
                        <div class="text-[10px] text-slate-500">24h 动量</div>
                        <div class="text-xs font-mono font-bold {chg24_c} mt-0.5">{'+' if chg24>=0 else ''}{chg24:.1f}%</div>
                    </div>
                    <div>
                        <div class="text-[10px] text-slate-500">7d 趋势</div>
                        <div class="text-xs font-mono font-bold {chg7d_c} mt-0.5">{'+' if chg7d>=0 else ''}{chg7d:.1f}%</div>
                    </div>
                    <div>
                        <div class="text-[10px] text-slate-500">24h 换手率</div>
                        <div class="text-xs font-mono font-bold text-indigo-400 mt-0.5">{p.get('换手率(%)', '-')}%</div>
                    </div>
                    <div>
                        <div class="text-[10px] text-slate-500">流通市值</div>
                        <div class="text-xs font-mono font-bold text-slate-200 mt-0.5">${p.get('流通市值(万)', '-')}万</div>
                    </div>
                    <div>
                        <div class="text-[10px] text-slate-500">MC/FDV流通</div>
                        <div class="text-xs font-mono font-bold text-emerald-400 mt-0.5">{p.get('流通率(%)', '-')}%</div>
                    </div>
                </div>

                <!-- 多智能体辩论裁决报告 -->
                <div class="text-xs text-slate-300 leading-relaxed bg-slate-950/50 p-3.5 rounded-xl border border-slate-800/60">
                    {report_html}
                </div>
            </div>

            <!-- 底部操作栏：一键看K线与链上数据 -->
            <div class="mt-4 pt-3 border-t border-slate-800/80 flex flex-wrap justify-between items-center gap-2 text-xs">
                <span class="text-slate-500 font-mono text-[11px]">更新: {p.get('发现时间', '')} | 距ATH: {p.get('距高点跌幅(%)', '-')}%</span>
                <div class="flex items-center gap-2">
                    <a href="{dex_url}" target="_blank" class="bg-slate-800 hover:bg-indigo-600 text-slate-200 hover:text-white px-3 py-1 rounded-lg transition font-medium">📈 DexScreener 链上K线</a>
                    <a href="{cg_url}" target="_blank" class="bg-slate-800 hover:bg-emerald-600 text-slate-200 hover:text-white px-3 py-1 rounded-lg transition font-medium">🦎 CoinGecko 详情</a>
                </div>
            </div>
        </div>"""

  html = f"""<!DOCTYPE html>
<html lang="zh-CN" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <title>Crypto Alpha Hunter V4.0 | 机构级 AI 投研终端</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen font-sans pb-20 selection:bg-indigo-500 selection:text-white">
    <!-- 顶部毛玻璃导航栏 -->
    <header class="border-b border-slate-800/80 bg-slate-900/80 backdrop-blur-md sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-4 py-3.5 flex flex-wrap justify-between items-center gap-3">
            <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-emerald-500 flex items-center justify-center text-xl shadow-lg">🦅</div>
                <div>
                    <div class="flex items-center gap-2.5">
                        <h1 class="font-black text-lg tracking-wider text-white">CRYPTO ALPHA HUNTER</h1>
                        <span class="bg-gradient-to-r from-indigo-500 to-emerald-500 text-slate-950 text-[11px] font-mono font-extrabold px-2 py-0.5 rounded-md">V4.0 双轮驱动版</span>
                    </div>
                    <p class="text-[11px] text-slate-400">全网热搜 Meme 异动直通车 · 主流赛道反弹雷达 · 多智能体投委会</p>
                </div>
            </div>
            <div class="flex items-center gap-4">
                <div class="text-right hidden sm:block">
                    <div class="text-[10px] text-slate-500">最后巡航时间 (北京时间)</div>
                    <div class="text-xs text-emerald-400 font-mono font-bold">{bj_now}</div>
                </div>
                <a href="{config.FEISHU_URL}" target="_blank" class="bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold px-4 py-2.5 rounded-xl shadow-lg transition">
                    ⚙️ 飞书控制台
                </a>
            </div>
        </div>
    </header>

    <main class="max-w-7xl mx-auto px-4 mt-6 space-y-7">
        <!-- 模块1：五大引擎实时状态灯 + 头条警报 -->
        <section class="grid grid-cols-1 lg:grid-cols-4 gap-4">
            <div class="lg:col-span-3 grid grid-cols-2 sm:grid-cols-5 gap-2.5">
                {api_html}
            </div>
            <div class="bg-gradient-to-br from-indigo-950/60 to-slate-900 border border-indigo-500/40 rounded-xl p-3.5 flex flex-col justify-between">
                <div class="flex justify-between items-center">
                    <span class="text-xs font-extrabold text-indigo-300">⚡ 最新 Alpha 警报</span>
                    <span class="text-[10px] text-slate-400 font-mono">{alert.get('time', '')}</span>
                </div>
                <div class="text-xs font-bold text-white mt-1 truncate">{alert.get('title', '')}</div>
                <div class="text-[11px] text-slate-300 mt-0.5 line-clamp-2">{alert.get('content', '')}</div>
            </div>
        </section>

        <!-- 模块2：全网叙事风向标 & 一二级市场情报 -->
        <section class="grid grid-cols-1 lg:grid-cols-12 gap-4">
            <div class="lg:col-span-7 bg-slate-900/70 border border-slate-800 rounded-2xl p-4">
                <h2 class="text-sm font-extrabold text-white mb-3 flex items-center gap-2">
                    <span>🔥 全网热搜叙事词云 & 异动风向标</span>
                </h2>
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                    {kw_html if kw_html else '<div class="text-xs text-slate-500">正在嗅探全网热词...</div>'}
                </div>
            </div>
            <div class="lg:col-span-5 bg-slate-900/70 border border-slate-800 rounded-2xl p-4">
                <h2 class="text-sm font-extrabold text-white mb-2 flex items-center gap-2">
                    <span>💰 实时热搜飙升、VC 融资与媒体快讯</span>
                </h2>
                <ul class="max-h-48 overflow-y-auto pr-1">{news_html if news_html else '<li class="text-xs text-slate-500">正在同步快讯...</li>'}</ul>
            </div>
        </section>

        <!-- 模块3：主流赛道轮动与反弹雷达 -->
        <section>
            <div class="flex justify-between items-center mb-3">
                <h2 class="text-base font-extrabold text-white flex items-center gap-2">
                    <span>📡 核心赛道反弹与资金轮动雷达 (已自动过滤稳定币与包装币 · 共 {len(tracks)} 个)</span>
                </h2>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                {radar_html}
            </div>
        </section>

        <!-- 模块4：多智能体精选项目库 (带交互式分类 Tab) -->
        <section>
            <div class="flex flex-wrap justify-between items-center gap-3 mb-4">
                <h2 class="text-base font-extrabold text-white flex items-center gap-2">
                    <span>💎 多智能体投委会精选 Alpha 标的库 (共 {len(projects)} 个)</span>
                </h2>
                <!-- 交互式分类筛选按钮 -->
                <div class="flex items-center gap-2 bg-slate-900 p-1 rounded-xl border border-slate-800 text-xs">
                    <button onclick="filterProjects('all')" id="tab-all" class="tab-btn bg-indigo-600 text-white font-bold px-3 py-1.5 rounded-lg transition">全部 ({len(projects)})</button>
                    <button onclick="filterProjects('meme')" id="tab-meme" class="tab-btn text-slate-400 hover:text-white px-3 py-1.5 rounded-lg transition">🔥 热门Meme/异动</button>
                    <button onclick="filterProjects('rebound')" id="tab-rebound" class="tab-btn text-slate-400 hover:text-white px-3 py-1.5 rounded-lg transition">📈 赛道反弹龙头</button>
                    <button onclick="filterProjects('value')" id="tab-value" class="tab-btn text-slate-400 hover:text-white px-3 py-1.5 rounded-lg transition">💎 底部价值潜伏</button>
                </div>
            </div>
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {alpha_html if alpha_html else '<div class="text-slate-400 text-sm py-8 text-center bg-slate-900/50 rounded-2xl border border-slate-800 col-span-2">正在运行双轮驱动选币引擎，请稍候刷新...</div>'}
            </div>
        </section>
    </main>

    <script>
        function filterProjects(cat) {{
            document.querySelectorAll('.tab-btn').forEach(btn => {{
                btn.classList.remove('bg-indigo-600', 'text-white', 'font-bold');
                btn.classList.add('text-slate-400');
            }});
            const activeBtn = document.getElementById('tab-' + cat);
            activeBtn.classList.add('bg-indigo-600', 'text-white', 'font-bold');
            activeBtn.classList.remove('text-slate-400');

            document.querySelectorAll('.project-card').forEach(card => {{
                if (cat === 'all' || card.dataset.category === cat) {{
                    card.style.display = 'flex';
                }} else {{
                    card.style.display = 'none';
                }}
            }});
        }}
    </script>
</body>
</html>"""

  with open("docs/index.html", "w", encoding="utf-8") as f:
    f.write(html)
  print("✅ V4.0 网站看板编译完成: docs/index.html")


if __name__ == "__main__":
  build_dashboard()
