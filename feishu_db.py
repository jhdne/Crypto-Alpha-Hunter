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
from logger import get_logger
from models import normalize_project

log = get_logger("feishu_db")
_SESSION = requests.Session()
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
        resp = _SESSION.post(url, json=payload, timeout=10).json()
        if resp.get("code") == 0:
            token = resp.get("tenant_access_token")
            _TOKEN_CACHE["token"] = token
            _TOKEN_CACHE["expire"] = now + resp.get("expire", 7200) - 300
            return token
        log.warning("飞书鉴权失败: %s", resp.get("msg"))
    except Exception as e:
        log.warning("获取飞书 Token 异常: %s", e)
    return None


def _get_table_field_types(token, table_id):
    """查询飞书多维表格现有的列及其类型，缓存避免重复请求"""
    if table_id in _FIELD_TYPES_CACHE:
        return _FIELD_TYPES_CACHE[table_id]

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{table_id}/fields"
    headers = {"Authorization": f"Bearer {token}"}
    field_map = {}
    try:
        resp = _SESSION.get(url, headers=headers, timeout=10).json()
        if resp.get("code") == 0:
            items = resp.get("data", {}).get("items", []) or []
            for item in items:
                field_map[item.get("field_name")] = item.get("type")
            _FIELD_TYPES_CACHE[table_id] = field_map
    except Exception as e:
        log.warning("获取表字段结构异常 (%s): %s", table_id, e)
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
                res = _SESSION.post(
                    url, headers=headers, json={"field_name": k, "type": f_type}, timeout=10
                ).json()
                if res.get("code") == 0:
                    existing[k] = f_type
            except Exception as e:
                log.debug("自动创建字段 %s 失败: %s", k, e)
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


def get_records(table_id, page_size=100, max_pages=5):
    """读取指定飞书多维表格记录（支持分页）"""
    token = get_tenant_access_token()
    if not token or not FEISHU_APP_TOKEN or not table_id:
        return []

    base_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    all_items = []
    page_token = ""

    for _ in range(max_pages):
        params = {"page_size": page_size}
        if page_token:
            params["page_token"] = page_token
        try:
            resp = _SESSION.get(base_url, headers=headers, params=params, timeout=12).json()
            if resp.get("code") != 0:
                log.warning("读取飞书表 (%s) 失败: %s", table_id, resp.get("msg"))
                break
            data = resp.get("data", {}) or {}
            items = data.get("items", []) or []
            all_items.extend(items)
            if not data.get("has_more") or not data.get("page_token"):
                break
            page_token = data["page_token"]
        except Exception as e:
            log.warning("读取飞书表异常 (%s): %s", table_id, e)
            break

    return all_items


def add_record(table_id, fields) -> bool:
    """向指定飞书多维表格新增一行记录"""
    token = get_tenant_access_token()
    if not token or not FEISHU_APP_TOKEN or not table_id:
        return False

    field_types = _ensure_fields_exist(token, table_id, fields)
    safe_fields = _coerce_fields_for_feishu(fields, field_types)

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = _SESSION.post(url, headers=headers, json={"fields": safe_fields}, timeout=12).json()
        if resp.get("code") == 0:
            return True
        log.warning("写入飞书表 (%s) 失败: %s", table_id, resp.get("msg"))
    except Exception as e:
        log.warning("写入飞书表异常 (%s): %s", table_id, e)
    return False


def update_record(table_id, record_id, fields) -> bool:
    """更新飞书多维表格中的指定记录"""
    token = get_tenant_access_token()
    if not token or not FEISHU_APP_TOKEN or not table_id or not record_id:
        return False

    field_types = _ensure_fields_exist(token, table_id, fields)
    safe_fields = _coerce_fields_for_feishu(fields, field_types)

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{table_id}/records/{record_id}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = _SESSION.put(url, headers=headers, json={"fields": safe_fields}, timeout=12).json()
        if resp.get("code") == 0:
            return True
        log.warning("更新飞书记录 (%s) 失败: %s", record_id, resp.get("msg"))
    except Exception as e:
        log.warning("更新飞书记录异常 (%s): %s", record_id, e)
    return False


class FeishuDB:
    """V6.1 飞书多维表格统一适配器（支持进化权重合并与完整分页）"""

    def __init__(self):
        self.token = get_tenant_access_token()

    def get_strategy_weights(self, local_evo_state: dict = None, *args, **kwargs) -> dict:
        """
        优先使用本地高频自进化权重，若未提供或飞书配置表有显式权重则解析并归一化。
        """
        default_weights = dict(DEFAULT_EVOLUTION_STATE["weights"])
        if isinstance(local_evo_state, dict) and isinstance(local_evo_state.get("weights"), dict):
            w = local_evo_state["weights"]
            if "early_timing" in w:
                return w

        if not TABLE_ID_CONFIG:
            return default_weights

        records = get_records(TABLE_ID_CONFIG, page_size=20, max_pages=1)
        if not records:
            return default_weights

        try:
            last_fields = records[-1].get("fields", {})
            key_mapping = {
                "early_timing": ["early_timing", "价格安全权重", "早期买点权重"],
                "buy_pressure": ["buy_pressure", "营销背书权重", "盘面量价权重", "买盘压力权重"],
                "mc_odds": ["mc_odds", "市值赔率权重"],
                "track_heat": ["track_heat", "赛道热度权重", "叙事热度权重"],
                "fundamentals": ["fundamentals", "技术实力权重", "基本面权重"],
            }
            parsed = {}
            for target_key, aliases in key_mapping.items():
                for alias in aliases:
                    if alias in last_fields and last_fields[alias] not in (None, ""):
                        val = float(str(last_fields[alias]).replace("%", "").strip())
                        parsed[target_key] = val / 100.0 if val > 1.0 else val
                        break
            if len(parsed) == len(default_weights):
                total = sum(max(v, 0.0) for v in parsed.values())
                if total > 0:
                    return {k: round(max(v, 0.0) / total, 3) for k, v in parsed.items()}
        except Exception as e:
            log.warning("解析飞书策略权重失败，使用默认进化权重: %s", e)

        return default_weights

    def get_approved_tracks(self, *args, **kwargs) -> list:
        """从 TABLE_ID_RADAR 读取近期嗅探到的热门赛道名称列表"""
        if not TABLE_ID_RADAR:
            return []

        records = get_records(TABLE_ID_RADAR, page_size=50, max_pages=2)
        tracks = []
        for r in records:
            f = r.get("fields", {})
            status = str(f.get("人工状态") or f.get("状态") or "")
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

        p = normalize_project(p_data)
        fields = {
            "代币名称": p["name"],
            "代币符号": p["symbol"],
            "项目类型": p["project_type"],
            "所属赛道": p["track"],
            "所在公链": p["chain"],
            "合约地址": p["contract"],
            "推荐时价格($)": p["price"],
            "实时价格($)": p["live_price"],
            "最高涨幅(%)": 0.0,
            "当前盈亏(%)": p["live_roi_pct"],
            "最大回撤(%)": p["max_drawdown_pct"],
            "市值($万)": p["mc_wan"],
            "24h交易量($万)": p["vol_wan"],
            "流动性($万)": p["liq_wan"],
            "1h涨跌幅(%)": p["chg_1h"],
            "24h涨跌幅(%)": p["chg_24h"],
            "24h买盘占比(%)": p["buy_ratio"],
            "池子创建时间(小时)": p["pool_age_hours"],
            "买点所处阶段": p["entry_timing"],
            "AI综合评分": p["score"],
            "近期催化剂": p["catalyst"],
            "AI投研简评": p["report"],
            "DEX链接": p["dex_url"],
            "发现时间": p["found_at"] or time.strftime("%Y-%m-%d %H:%M"),
        }
        return add_record(TABLE_ID_ALPHA, fields)
