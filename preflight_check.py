# preflight_check.py - 启动前校验模块与配置的完整性（缺失即退出并给出明确提示）
import importlib
import os
import sys

REQUIRED_NAMES = {
    "config": [
        "LLM_API_KEYS", "LLM_ENDPOINTS", "AGENT_MODEL_ROUTING",
        "DEFAULT_EVOLUTION_STATE", "FEISHU_APP_ID", "FEISHU_APP_SECRET",
        "FEISHU_APP_TOKEN", "TABLE_ID_CONFIG", "TABLE_ID_RADAR",
        "TABLE_ID_ALPHA", "FEISHU_URL", "COINGECKO_API_KEY", "TAVILY_API_KEY",
    ],
    "feishu_db": ["FeishuDB", "get_records", "add_record", "update_record"],
    "llm_engine": ["ask_ai", "call_llm", "extract_json", "multi_agent_evaluate"],
    "notifier": ["load_local_db", "save_local_db", "build_dashboard", "send_wechat"],
}

THIRD_PARTY = ["requests", "feedparser"]


def main():
    errors = []

    for mod_name in THIRD_PARTY:
        try:
            importlib.import_module(mod_name)
        except ImportError:
            errors.append(f"缺少第三方依赖: {mod_name}（请检查 requirements.txt）")

    for mod_name, names in REQUIRED_NAMES.items():
        try:
            mod = importlib.import_module(mod_name)
        except Exception as e:
            errors.append(f"模块 {mod_name}.py 无法导入: {e}")
            continue
        for name in names:
            if not hasattr(mod, name):
                errors.append(f"{mod_name}.py 缺少必需的名称: {name}")

    if errors:
        print("❌ 启动前自检失败：")
        for e in errors:
            print(f"   - {e}")
        sys.exit(1)

    import config
    if not config.LLM_API_KEYS.get("glm") and not config.LLM_API_KEYS.get("groq"):
        print("⚠️ 警告：GLM_API_KEY 与 GROQ_API_KEY 均未配置，AI 将使用量化保底逻辑。")
    if not config.FEISHU_APP_ID:
        print("⚠️ 提示：未配置飞书，将仅使用本地 docs/alpha_db.json 双引擎。")

    print("✅ 启动前自检通过：所有模块与配置名称完整。")


if __name__ == "__main__":
    main()
