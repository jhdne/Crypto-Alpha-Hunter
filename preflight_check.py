import importlib
import inspect
import sys


def check_module_attrs(mod_name: str, required_attrs: list) -> list:
    errors = []
    try:
        mod = importlib.import_module(mod_name)
    except Exception as e:
        return [f"模块 {mod_name} 导入失败: {e}"]

    for attr in required_attrs:
        if not hasattr(mod, attr):
            errors.append(f"模块 {mod_name} 缺少必需属性/函数: {attr}")
    return errors


def main():
    print("🔍 [Preflight Check] 正在校验 V6.0 模块接口与配置完整性...")
    all_errors = []

    for pkg in ("requests", "feedparser"):
        try:
            importlib.import_module(pkg)
        except ImportError:
            all_errors.append(f"缺少第三方依赖包: {pkg} (请检查 requirements.txt)")

    all_errors.extend(
        check_module_attrs(
            "config",
            [
                "LLM_API_KEYS",
                "LLM_ENDPOINTS",
                "AGENT_MODEL_ROUTING",
                "DEFAULT_EVOLUTION_STATE",
                "FEISHU_APP_ID",
                "FEISHU_APP_SECRET",
                "FEISHU_APP_TOKEN",
                "TABLE_ID_CONFIG",
                "TABLE_ID_RADAR",
                "TABLE_ID_ALPHA",
                "FEISHU_URL",
                "COINGECKO_API_KEY",
                "TAVILY_API_KEY",
            ],
        )
    )

    all_errors.extend(
        check_module_attrs(
            "feishu_db",
            ["get_records", "add_record", "update_record", "FeishuDB"],
        )
    )

    all_errors.extend(
        check_module_attrs(
            "llm_engine",
            ["call_llm", "ask_ai", "extract_json", "multi_agent_evaluate"],
        )
    )

    all_errors.extend(
        check_module_attrs("notifier", ["build_dashboard"])
    )

    # 校验方法参数签名是否支持 V6.0
    try:
        import feishu_db
        sig = inspect.signature(feishu_db.FeishuDB.get_strategy_weights)
        if len(sig.parameters) < 2:
            print("⚠️ 提示: feishu_db.FeishuDB.get_strategy_weights 为旧版单参数签名，建议同步更新 feishu_db.py")
    except Exception:
        pass

    if all_errors:
        print("❌ 启动前自检发现以下问题:")
        for err in all_errors:
            print(f"   - {err}")
        sys.exit(1)

    print("✅ [Preflight Check] 所有 V6.0 模块接口与配置自检通过！")


if __name__ == "__main__":
    main()
