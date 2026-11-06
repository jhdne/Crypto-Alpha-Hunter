# notifier.py - 静态网站看板生成器 (自动生成 docs/index.html 供 GitHub Pages 托管)
from datetime import datetime, timedelta, timezone
import json
import os
import config
import feishu_db

ALERT_CACHE_FILE = "docs/latest_alert.json"


def _safe_float(val, default=0.0):
  """安全转换为浮点数，防止飞书表格中有空格子或非数字导致报错"""
  try:
    if val is None or val == "":
      return default
    return float(val)
  except Exception:
    return default


def update_alert_and_build(title, md_content):
  """记录最新系统广播并立刻重新编译生成网站看板"""
  os.makedirs("docs", exist_ok=True)
  bj_time = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime(
      "%Y-%m-%d %H:%M"
  )
  with open(ALERT_CACHE_FILE, "w", encoding="utf-8") as f:
    json.dump(
        {"title": str(title), "content": str(md_content), "time": bj_time},
        f,
        ensure_ascii=False,
    )
  build_dashboard()


# === 兼容所有脚本的通知函数名入口 ===
def send_wechat(title, md_content):
  update_alert_and_build(title, md_content)


def send_email(title, md_content):
  update_alert_and_build(title, md_content)


def build_dashboard():
  """从飞书多维表格拉取3张表的最新数据，编译生成 docs/index.html"""
  print("🌐 正在编译生成 Web 投研看板 (docs/index.html)...")
  os.makedirs("docs", exist_ok=True)
  bj_now = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime(
      "%Y-%m-%d %H:%M:%S"
  )

  # 1. 读取最新广播消息
  latest_alert = {
      "title": "系统运行正常",
      "content": "AI 投研智能体正在 24 小时巡航中...",
      "time": bj_now,
  }
  if os.path.exists(ALERT_CACHE_FILE):
    try:
      with open(ALERT_CACHE_FILE, "r", encoding="utf-8") as f:
        latest_alert = json.load(f)
    except Exception:
      pass

  # 2. 从飞书读取三张表数据
  cfg_list = feishu_db.get_records(config.TABLE_ID_CONFIG)
  weights = cfg_list[0].get("fields", {}) if cfg_list else {}

  radar_list = [
      r.get("fields", {})
      for r in feishu_db.get_records(config.TABLE_ID_RADAR)
      if r.get("fields")
  ]
  alpha_list = [
      r.get("fields", {})
      for r in feishu_db.get_records(config.TABLE_ID_ALPHA)
      if r.get("fields")
  ]
  # 按综合总分从高到低排序项目
  alpha_list.sort(
      key=lambda x: _safe_float(x.get("综合总分"), 0), reverse=True
  )

  # 3. 组装赛道 HTML 卡片
  radar_html = ""
  for t in radar_list:
    if not t.get("赛道名称") and not t.get("赛道ID"):
      continue
    status = str(t.get("人工状态", "允许深挖"))
    badge_color = (
        "bg-emerald-500/20 text-emerald-400 border-emerald-500/30"
        if status == "允许深挖"
        else "bg-slate-700 text-slate-400"
    )
    chg = _safe_float(t.get("24h涨幅(%)"), 0.0)
    chg_str = f"+{chg:.1f}%" if chg >= 0 else f"{chg:.1f}%"
    chg_color = "text-emerald-400" if chg >= 0 else "text-rose-400"

    radar_html += f"""
        <div class="bg-slate-900/90 border border-slate-800 rounded-xl p-4 hover:border-indigo-500/50 transition">
            <div class="flex justify-between items-start mb-2">
                <div>
                    <h3 class="font-bold text-white text-base">{t.get('赛道名称', '未知')}</h3>
                    <span class="text-xs text-slate-500 font-mono">{t.get('赛道ID', '')}</span>
                </div>
                <span class="text-xs px-2 py-0.5 rounded border {badge_color}">{status}</span>
            </div>
            <div class="flex items-center gap-3 my-2 text-xs">
                <span class="bg-slate-800 px-2 py-1 rounded text-slate-300">来源: {t.get('发现来源', '-')}</span>
                <span class="font-mono font-bold {chg_color}">24h: {chg_str}</span>
            </div>
            <p class="text-xs text-slate-400 leading-relaxed mt-2">{t.get('AI赛道简评', '')}</p>
        </div>
        """

  # 4. 组装精选项目 HTML 卡片
  alpha_html = ""
  for p in alpha_list:
    if not p.get("代币符号") and not p.get("项目ID"):
      continue
    score = _safe_float(p.get("综合总分"), 0.0)
    score_style = (
        "bg-emerald-500 text-slate-950"
        if score >= 80
        else (
            "bg-indigo-500 text-white"
            if score >= 70
            else "bg-slate-700 text-slate-200"
        )
    )
    roi = p.get("7日真实涨幅(%)")
    roi_badge = ""
    if roi is not None and roi != "":
      roi_val = _safe_float(roi, 0.0)
      roi_c = (
          "text-emerald-400 bg-emerald-500/10"
          if roi_val >= 0
          else "text-rose-400 bg-rose-500/10"
      )
      roi_badge = (
          f'<span class="text-xs px-2 py-1 rounded font-mono {roi_c}">7日回测:'
          f" {'+' if roi_val>=0 else ''}{roi_val}%</span>"
      )

    report_html = str(p.get("多智能体投研报告", "")).replace("\n", "<br>")

    alpha_html += f"""
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 hover:border-indigo-500/60 transition flex flex-col justify-between">
            <div>
                <div class="flex justify-between items-center mb-3">
                    <div class="flex items-center gap-2">
                        <span class="text-xl font-extrabold text-white">{p.get('代币符号', '')}</span>
                        <span class="text-xs bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 px-2 py-0.5 rounded">{p.get('所属赛道', '')}</span>
                        {roi_badge}
                    </div>
                    <div class="px-3 py-1 rounded-lg font-mono font-black text-sm {score_style}">
                        {score} 分
                    </div>
                </div>
                <div class="grid grid-cols-4 gap-2 bg-slate-950/70 p-3 rounded-lg border border-slate-800/80 mb-4 text-center">
                    <div>
                        <div class="text-[11px] text-slate-500">推荐时价格</div>
                        <div class="text-xs font-mono font-bold text-slate-200">${p.get('推荐时价格', '-')}</div>
                    </div>
                    <div>
                        <div class="text-[11px] text-slate-500">流通市值</div>
                        <div class="text-xs font-mono font-bold text-slate-200">${p.get('流通市值(万)', '-')}万</div>
                    </div>
                    <div>
                        <div class="text-[11px] text-slate-500">MC/FDV流通率</div>
                        <div class="text-xs font-mono font-bold text-emerald-400">{p.get('流通率(%)', '-')}%</div>
                    </div>
                    <div>
                        <div class="text-[11px] text-slate-500">距ATH高点跌幅</div>
                        <div class="text-xs font-mono font-bold text-amber-400">{p.get('距高点跌幅(%)', '-')}%</div>
                    </div>
                </div>
                <div class="text-xs text-slate-300 leading-relaxed bg-slate-950/40 p-3.5 rounded-lg border border-slate-800/50">
                    {report_html}
                </div>
            </div>
            <div class="mt-3 pt-2 border-t border-slate-800/60 flex justify-between items-center text-[11px] text-slate-500">
                <span>ID: {p.get('项目ID', '')}</span>
                <span>发掘时间: {p.get('发现时间', '')}</span>
            </div>
        </div>
        """

  # 5. 生成完整 HTML 页面
  html_content = f"""<!DOCTYPE html>
<html lang="zh-CN" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Crypto Alpha Hunter | AI 投研终端</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen font-sans pb-16">
    <header class="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-4 py-3.5 flex flex-wrap justify-between items-center gap-3">
            <div class="flex items-center gap-3">
                <span class="text-2xl">🦅</span>
                <div>
                    <h1 class="font-extrabold text-lg tracking-wide text-white">CRYPTO ALPHA HUNTER</h1>
                    <p class="text-[11px] text-slate-400">全自动赛道嗅探 · 多智能体博弈投委会 · 自我进化终端</p>
                </div>
            </div>
            <div class="flex items-center gap-4">
                <span class="text-xs text-slate-400 font-mono">最后更新(北京时间): {bj_now}</span>
                <a href="{config.FEISHU_URL}" target="_blank" class="bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold px-4 py-2 rounded-lg transition">
                    ⚙️ 打开飞书控制台
                </a>
            </div>
        </div>
    </header>

    <main class="max-w-7xl mx-auto px-4 mt-6 space-y-8">
        <section class="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div class="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-xl p-4">
                <div class="text-xs font-bold text-indigo-400 mb-3 flex justify-between">
                    <span>🧬 当前自进化策略权重 (表1: {weights.get('策略名称', '默认策略')})</span>
                    <span class="text-slate-400 font-mono">市值区间: ${weights.get('最低市值(万美元)', 500)}万 ~ ${weights.get('最高市值(万美元)', 15000)}万</span>
                </div>
                <div class="grid grid-cols-5 gap-2 text-center">
                    <div class="bg-slate-950 p-2.5 rounded-lg border border-slate-800">
                        <div class="text-[11px] text-slate-400">赛道热度</div>
                        <div class="text-base font-mono font-bold text-white mt-0.5">{weights.get('赛道热度权重', 20)}%</div>
                    </div>
                    <div class="bg-slate-950 p-2.5 rounded-lg border border-slate-800">
                        <div class="text-[11px] text-slate-400">价格安全垫</div>
                        <div class="text-base font-mono font-bold text-emerald-400 mt-0.5">{weights.get('价格安全权重', 30)}%</div>
                    </div>
                    <div class="bg-slate-950 p-2.5 rounded-lg border border-slate-800">
                        <div class="text-[11px] text-slate-400">GitHub技术</div>
                        <div class="text-base font-mono font-bold text-white mt-0.5">{weights.get('技术实力权重', 15)}%</div>
                    </div>
                    <div class="bg-slate-950 p-2.5 rounded-lg border border-slate-800">
                        <div class="text-[11px] text-slate-400">VC与营销背书</div>
                        <div class="text-base font-mono font-bold text-amber-400 mt-0.5">{weights.get('营销背书权重', 20)}%</div>
                    </div>
                    <div class="bg-slate-950 p-2.5 rounded-lg border border-slate-800">
                        <div class="text-[11px] text-slate-400">市值与解锁赔率</div>
                        <div class="text-base font-mono font-bold text-white mt-0.5">{weights.get('市值赔率权重', 15)}%</div>
                    </div>
                </div>
            </div>
            <div class="bg-indigo-950/30 border border-indigo-500/30 rounded-xl p-4 flex flex-col justify-between">
                <div class="flex justify-between items-center">
                    <span class="text-xs font-bold text-indigo-300">📢 最新系统广播</span>
                    <span class="text-[11px] text-slate-400 font-mono">{latest_alert['time']}</span>
                </div>
                <div class="my-2 text-sm font-bold text-white">{latest_alert['title']}</div>
                <div class="text-xs text-slate-300 line-clamp-2">{latest_alert['content']}</div>
            </div>
        </section>

        <section>
            <h2 class="text-base font-bold text-white mb-3 flex items-center gap-2">
                <span>📡 热门与潜力赛道雷达 (共 {len(radar_list)} 个)</span>
            </h2>
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                {radar_html if radar_html else '<div class="text-slate-500 text-sm">暂无赛道数据，请运行 track 任务</div>'}
            </div>
        </section>

        <section>
            <h2 class="text-base font-bold text-white mb-3 flex items-center gap-2">
                <span>💎 多智能体投委会精选项目库 (按综合得分排序 · 共 {len(alpha_list)} 个)</span>
            </h2>
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {alpha_html if alpha_html else '<div class="text-slate-500 text-sm">暂无精选项目，请运行 project 任务</div>'}
            </div>
        </section>
    </main>
</body>
</html>"""

  with open("docs/index.html", "w", encoding="utf-8") as f:
    f.write(html_content)
  print("✅ 网站看板编译完成: docs/index.html")


if __name__ == "__main__":
  build_dashboard()
