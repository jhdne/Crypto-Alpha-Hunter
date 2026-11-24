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


def check_func_params(mod_name: str, func_name: str, required_params: list) -> list:
    errors = []
    try:
        mod = importlib.import_module(mod_name)
        func = getattr(mod, func_name)
        sig = inspect.signature(func)
        for p in required_params:
            if p not in sig.parameters:
                errors.append(f"{mod_name}.{func_name} 缺少参数: {p}")
    except Exception as e:
        errors.append(f"校验 {mod_name}.{func_name} 签名失败: {e}")
    return errors


def main():
    print("🔍 [Preflight Check] 正在校验 V6.1 模块接口、函数签名与配置完整性...")
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
                "FEISHU_DASHBOARD_URL",
                "FEISHU_WEBHOOK_URL",
                "COINGECKO_API_KEY",
                "TAVILY_API_KEY",
            ],
        )
    )

    all_errors.extend(check_module_attrs("logger", ["get_logger"]))
    all_errors.extend(check_module_attrs("models", ["normalize_project", "project_unique_key"]))
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
    all_errors.extend(check_module_attrs("notifier", ["build_dashboard", "load_local_db", "save_local_db"]))

    # 校验关键函数签名
    all_errors.extend(check_func_params("llm_engine", "ask_ai", ["prompt", "role", "json_mode"]))
    all_errors.extend(check_func_params("llm_engine", "call_llm", ["agent_role", "json_mode"]))
    all_errors.extend(check_func_params("llm_engine", "multi_agent_evaluate", ["project_data", "evolution_state"]))

    try:
        import feishu_db
        sig = inspect.signature(feishu_db.FeishuDB.get_strategy_weights)
        if len(sig.parameters) < 2:
            all_errors.append("feishu_db.FeishuDB.get_strategy_weights 缺少 local_evo_state 参数")
    except Exception as e:
        all_errors.append(f"校验 FeishuDB.get_strategy_weights 失败: {e}")

    if all_errors:
        print("❌ 启动前自检发现以下问题:")
        for err in all_errors:
            print(f"   - {err}")
        sys.exit(1)

    print("✅ [Preflight Check] 所有 V6.1 模块接口、签名与配置自检通过！")


if __name__ == "__main__":
    main()
