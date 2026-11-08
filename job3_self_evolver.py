# job3_self_evolver.py - V5.0 市场真相回测与策略权重自我进化
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

    # 1. 优先通过 CoinGecko 查询
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

    # 2. 链上 Meme 或无 CG ID 的项目通过 DexScreener 查询最新价
    query = contract_address or symbol
    if query:
        try:
            d_res = requests.get(
                f"https://api.dexscreener.com/latest/dex/search?q={query}",
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
    return None


def run():
    print("🧬 开始执行 Job3：市场真相回测与权重自我进化...")
    alpha_records = feishu_db.get_records(config.TABLE_ID_ALPHA)
    if len(alpha_records) < 3:
        print("历史样本不足3个，暂不触发进化。")
        return

    performance_summary = []
    for r in alpha_records[:25]:
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
            performance_summary.append(
                f"- ${symbol}: 推荐后真实涨跌幅 {roi}% | 当时综合分: {_safe_str(fields.get('综合总分'))} "
                f"| 流通市值: {_safe_str(fields.get('流通市值(万)'))}万 | 机会类型: {_safe_str(fields.get('机会类型'))}"
            )

    if not performance_summary:
        print("⚠️ 未能获取到有效回测价格样本，跳过本次权重调整。")
        return

    cfg_records = feishu_db.get_records(config.TABLE_ID_CONFIG)
    if not cfg_records:
        print("⚠️ 飞书策略配置表为空，跳过权重更新。")
        return

    curr_w = cfg_records[0].get("fields", {})
    cfg_record_id = cfg_records[0]["record_id"]

    prompt = f"""
以下是我们投研系统近期选出项目的真实市场表现回测：
{chr(10).join(performance_summary)}

当前飞书策略表中的权重配置为：{curr_w}
请深入反思上述盈利与亏损项目的共同特征，微调我们的5项评分权重（单次调整幅度不超过10，且5项权重之和必须严格等于100）。
严格输出纯 JSON 格式：
{{
    "赛道热度权重": 25,
    "价格安全权重": 25,
    "技术实力权重": 15,
    "营销背书权重": 20,
    "市值赔率权重": 15,
    "evolution_reason": "用100字说明本周市场风格变化及权重调整原因"
}}
"""
    raw_resp = llm_engine.ask_ai(prompt, role="evolver_agent", json_mode=True)
    new_w = llm_engine.extract_json(raw_resp)
    if not isinstance(new_w, dict) or "赛道热度权重" not in new_w:
        print("⚠️ AI 返回的进化权重格式无效，保持原权重。")
        return

    reason = new_w.pop("evolution_reason", "完成常规市场回测进化")
    feishu_db.update_record(config.TABLE_ID_CONFIG, cfg_record_id, new_w)
    notifier.send_wechat(
        "🧬 智能体已完成本周自我进化调参！",
        f"**进化复盘结论：**\n{reason}\n\n**最新权重已自动写入飞书表1：**\n`{new_w}`",
    )


if __name__ == "__main__":
    run()
