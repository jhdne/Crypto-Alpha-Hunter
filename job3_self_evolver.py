# job3_self_evolver.py
import config
import feishu_db
import llm_engine
import notifier
import requests


def run():
  print("🧬 开始执行 Job3：市场真相回测与权重自我进化...")
  alpha_records = feishu_db.get_records(config.TABLE_ID_ALPHA)
  if len(alpha_records) < 3:
    print("历史样本不足3个，暂不触发进化。")
    return

  performance_summary = []
  for r in alpha_records:
    fields = r.get("fields", {})
    coin_id = fields.get("项目ID")
    old_price = fields.get("推荐时价格")
    if not coin_id or not old_price:
      continue

    res = requests.get(
        f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd",
        timeout=15,
    ).json()
    new_price = res.get(coin_id, {}).get("usd")
    if new_price:
      roi = round((new_price - old_price) / old_price * 100, 2)
      feishu_db.update_record(
          config.TABLE_ID_ALPHA,
          r["record_id"],
          {"7日后价格": new_price, "7日真实涨幅(%)": roi},
      )
      performance_summary.append(
          f"- {fields.get('代币符号')}: 推荐后真实涨跌幅 {roi}% | 当时综合分:"
          f" {fields.get('综合总分')} | 流通市值:{fields.get('流通市值(万)')}万"
          f" | 距高点跌幅:{fields.get('距高点跌幅(%)')}%"
      )

  # 读取当前飞书表1的权重
  cfg_records = feishu_db.get_records(config.TABLE_ID_CONFIG)
  if not cfg_records:
    return
  curr_w = cfg_records[0]["fields"]
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
  new_w = llm_engine.extract_json(llm_engine.ask_ai(prompt, role="evolver_agent"))
  reason = new_w.pop("evolution_reason", "完成常规进化")

  feishu_db.update_record(config.TABLE_ID_CONFIG, cfg_record_id, new_w)
  notifier.send_wechat(
      "🧬 智能体已完成本周自我进化调参！",
      f"**进化复盘结论：**\n{reason}\n\n**最新权重已自动写入飞书表1：**\n`{new_w}`",
  )


if __name__ == "__main__":
  run()