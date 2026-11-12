import time
import requests
from config import (
    FEISHU_APP_ID,
    FEISHU_APP_SECRET,
    FEISHU_APP_TOKEN,
    TABLE_ID_CONFIG,
    TABLE_ID_RADAR,
    TABLE_ID_ALPHA,
    DEFAULT_EVOLUTION_STATE,
)

_TOKEN_CACHE = {"token": None, "expire": 0}
_FIELD_TYPES_CACHE = {}


def get_tenant_access_token():
    """获取并缓存飞书 tenant_access_token"""
    now = time.time()
    if _TOKEN_CACHE["token"] and now < _TOKEN_CACHE["expire"]:
        return _TOKEN_CACHE["token"]

    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        return None

    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}
    try:
        resp = requests.post(url, json=payload, timeout=10).json()
        if resp.get("code") == 0:
            token = resp.get("tenant_access_token")
            _TOKEN_CACHE["token"] = token
            _TOKEN_CACHE["expire"] = now + resp.get("expire", 7200) - 300
            return token
        else:
            print(f"⚠️ 飞书鉴权失败: {resp.get('msg')}")
    except Exception as e:
        print(f"⚠️ 获取飞书 Token 异常: {e}")
    return None


def _get_table_field_types(token, table_id):
    """查询飞书多维表格现有的列及其类型，缓存避免重复请求"""
    if table_id in _FIELD_TYPES_CACHE:
        return _FIELD_TYPES_CACHE[table_id]

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{table_id}/fields"
    headers = {"Authorization": f"Bearer {token}"}
    field_map = {}
    try:
        resp = requests.get(url, headers=headers, timeout=10).json()
        if resp.get("code") == 0:
            items = resp.get("data", {}).get("items", []) or []
            for item in items:
                field_map[item.get("field_name")] = item.get("type")
            _FIELD_TYPES_CACHE[table_id] = field_map
    except Exception as e:
        print(f"⚠️ 获取表字段结构异常 ({table_id}): {e}")
    return field_map


def _ensure_fields_exist(token, table_id, fields_dict):
    """如果多维表格缺少对应列，自动创建列（根据值的类型推断文本/数字列）"""
    if not token or not FEISHU_APP_TOKEN or not table_id:
        return {}

    existing = _get_table_field_types(token, table_id)
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{table_id}/fields"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    for k, v in fields_dict.items():
        if k not in existing:
            f_type = 2 if isinstance(v, (int, float)) and not isinstance(v, bool) else 1
            try:
                res = requests.post(
                    url, headers=headers, json={"field_name": k, "type": f_type}, timeout=10
                ).json()
                if res.get("code") == 0:
                    existing[k] = f_type
            except Exception:
                pass
    _FIELD_TYPES_CACHE[table_id] = existing
    return existing


def _coerce_fields_for_feishu(fields_dict, field_types):
    """根据多维表格中实际的字段类型，安全转换数据类型，避免 NumberFieldConvFail"""
    cleaned = {}
    for k, v in fields_dict.items():
        if v is None:
            continue
        expected_type = field_types.get(k)
        if expected_type == 2:  # 数字列
            try:
                if isinstance(v, str):
                    v_clean = (
                        v.replace("%", "")
                        .replace("$", "")
                        .replace(",", "")
                        .replace("+", "")
                        .strip()
                    )
                    cleaned[k] = float(v_clean) if v_clean else 0.0
                else:
                    cleaned[k] = float(v)
            except Exception:
                cleaned[k] = 0.0
        elif expected_type == 1:  # 文本列
            cleaned[k] = str(v)
        else:
            cleaned[k] = v
    return cleaned


def get_records(table_id, page_size=100):
    """读取指定飞书多维表格记录"""
    token = get_tenant_access_token()
    if not token or not FEISHU_APP_TOKEN or not table_id:
        return []

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{table_id}/records?page_size={page_size}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.get(url, headers=headers, timeout=12).json()
        if resp.get("code") == 0:
            return resp.get("data", {}).get("items", []) or []
        else:
            print(f"⚠️ 读取飞书表 ({table_id}) 失败: {resp.get('msg')}")
    except Exception as e:
        print(f"⚠️ 读取飞书表异常 ({table_id}): {e}")
    return []


def add_record(table_id, fields):
    """向指定飞书多维表格新增一行记录"""
    token = get_tenant_access_token()
    if not token or not FEISHU_APP_TOKEN or not table_id:
        return False

    field_types = _ensure_fields_exist(token, table_id, fields)
    safe_fields = _coerce_fields_for_feishu(fields, field_types)

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = requests.post(url, headers=headers, json={"fields": safe_fields}, timeout=12).json()
        if resp.get("code") == 0:
            return True
        else:
            print(f"⚠️ 写入飞书表 ({table_id}) 失败: {resp.get('msg')}")
    except Exception as e:
        print(f"⚠️ 写入飞书表异常 ({table_id}): {e}")
    return False


def update_record(table_id, record_id, fields):
    """更新飞书多维表格中的指定记录"""
    token = get_tenant_access_token()
    if not token or not FEISHU_APP_TOKEN or not table_id or not record_id:
        return False

    field_types = _ensure_fields_exist(token, table_id, fields)
    safe_fields = _coerce_fields_for_feishu(fields, field_types)

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{table_id}/records/{record_id}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = requests.put(url, headers=headers, json={"fields": safe_fields}, timeout=12).json()
        if resp.get("code") == 0:
            return True
        else:
            print(f"⚠️ 更新飞书记录 ({record_id}) 失败: {resp.get('msg')}")
    except Exception as e:
        print(f"⚠️ 更新飞书记录异常 ({record_id}): {e}")
    return False


class FeishuDB:
    """V6.0 飞书多维表格统一适配器（支持进化权重合并）"""

    def __init__(self):
        self.token = get_tenant_access_token()

    def get_strategy_weights(self, local_evo_state: dict = None, *args, **kwargs) -> dict:
        """
        优先使用本地高频自进化权重（V6.0），若飞书配置表有最新进化记录则合并。
        支持无参或传入 local_evo_state 调用。
        """
        default_weights = dict(DEFAULT_EVOLUTION_STATE["weights"])
        if isinstance(local_evo_state, dict) and isinstance(local_evo_state.get("weights"), dict):
            w = local_evo_state["weights"]
            if "early_timing" in w:
                return w

        if not TABLE_ID_CONFIG:
            return default_weights

        records = get_records(TABLE_ID_CONFIG, page_size=20)
        if not records:
            return default_weights

        try:
            last_fields = records[-1].get("fields", {})
            if "盘面量价权重" in last_fields or "叙事热度权重" in last_fields:
                return default_weights
        except Exception as e:
            print(f"⚠️ 解析策略权重失败，使用默认进化权重: {e}")

        return default_weights

    def get_approved_tracks(self, *args, **kwargs) -> list:
        """从 TABLE_ID_RADAR 读取近期嗅探到的热门赛道名称列表"""
        if not TABLE_ID_RADAR:
            return []

        records = get_records(TABLE_ID_RADAR, page_size=50)
        tracks = []
        for r in records:
            f = r.get("fields", {})
            status = str(f.get("状态", ""))
            if status in ("拒绝", "已忽略", "屏蔽"):
                continue
            name = f.get("赛道名称") or f.get("name")
            if name and str(name) not in tracks:
                tracks.append(str(name))
        return tracks[:10]

    def save_alpha_project(self, p_data: dict, *args, **kwargs) -> bool:
        """将 Job2 挖掘出的早期 Alpha 标的保存到 TABLE_ID_ALPHA 供 Job3 持续跟踪回测"""
        if not TABLE_ID_ALPHA:
            return False

        fields = {
            "代币名称": str(p_data.get("name", "")),
            "代币符号": str(p_data.get("symbol", "")),
            "项目类型": str(p_data.get("project_type", "🌪️ 高波Meme")),
            "所属赛道": str(p_data.get("track", "")),
            "所在公链": str(p_data.get("chain", "")),
            "合约地址": str(p_data.get("contract", "")),
            "推荐时价格($)": float(p_data.get("price", 0.0) or 0.0),
            "实时价格($)": float(p_data.get("price", 0.0) or 0.0),
            "最高涨幅(%)": 0.0,
            "当前盈亏(%)": 0.0,
            "市值($万)": float(p_data.get("mc_wan", 0.0) or 0.0),
            "24h交易量($万)": float(p_data.get("vol_wan", 0.0) or 0.0),
            "流动性($万)": float(p_data.get("liq_wan", 0.0) or 0.0),
            "1h涨跌幅(%)": float(p_data.get("chg_1h", 0.0) or 0.0),
            "24h涨跌幅(%)": float(p_data.get("chg_24h", 0.0) or 0.0),
            "24h买盘占比(%)": float(p_data.get("buy_ratio", 50.0) or 50.0),
            "池子创建时间(小时)": float(p_data.get("pool_age_hours", 48.0) or 48.0),
            "买点所处阶段": str(p_data.get("entry_timing", "🟢 早期点火期")),
            "AI综合评分": float(p_data.get("score", 0.0) or 0.0),
            "近期催化剂": str(p_data.get("catalyst", "")),
            "AI投研简评": str(p_data.get("report", "")),
            "DEX链接": str(p_data.get("dex_url", "")),
            "发现时间": str(p_data.get("found_at", time.strftime("%Y-%m-%d %H:%M"))),
        }
        return add_record(TABLE_ID_ALPHA, fields)
