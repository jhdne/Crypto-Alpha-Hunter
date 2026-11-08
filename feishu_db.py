# feishu_db.py - V5.0 完整自愈版（同时支持 FeishuDB 类与底层函数接口，带缓存与自动建列）
import time
import requests
import config

_TOKEN_CACHE = {"token": "", "expire_at": 0}
_FIELD_TYPES_CACHE = {}


def _get_headers():
    if not config.FEISHU_APP_ID or not config.FEISHU_APP_SECRET:
        return None
    now = time.time()
    if _TOKEN_CACHE["token"] and now < _TOKEN_CACHE["expire_at"]:
        return {
            "Authorization": f"Bearer {_TOKEN_CACHE['token']}",
            "Content-Type": "application/json",
        }
    try:
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        res = requests.post(
            url,
            json={
                "app_id": config.FEISHU_APP_ID,
                "app_secret": config.FEISHU_APP_SECRET,
            },
            timeout=10,
        ).json()
        token = res.get("tenant_access_token", "")
        if not token:
            return None
        _TOKEN_CACHE["token"] = token
        _TOKEN_CACHE["expire_at"] = now + int(res.get("expire", 7200)) - 300
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
    except Exception as e:
        print(f"⚠️ 获取飞书 Token 异常: {e}")
        return None


def get_records(table_id):
    headers = _get_headers()
    if not headers or not config.FEISHU_APP_TOKEN or not table_id:
        return []
    try:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{config.FEISHU_APP_TOKEN}/tables/{table_id}/records?page_size=100"
        res = requests.get(url, headers=headers, timeout=15).json()
        return res.get("data", {}).get("items", []) or []
    except Exception as e:
        print(f"⚠️ 飞书读取跳过: {e}")
        return []


def _prepare_fields(table_id, fields_dict, headers):
    if table_id not in _FIELD_TYPES_CACHE:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{config.FEISHU_APP_TOKEN}/tables/{table_id}/fields?page_size=100"
        res = requests.get(url, headers=headers, timeout=15).json()
        items = res.get("data", {}).get("items", []) or []
        _FIELD_TYPES_CACHE[table_id] = {i["field_name"]: i["type"] for i in items if "field_name" in i}

    col_types = _FIELD_TYPES_CACHE[table_id]
    clean_fields = {}

    for k, v in fields_dict.items():
        if v is None:
            continue
        if k not in col_types:
            f_type = 2 if isinstance(v, (int, float)) and not isinstance(v, bool) else 1
            try:
                c_res = requests.post(
                    f"https://open.feishu.cn/open-apis/bitable/v1/apps/{config.FEISHU_APP_TOKEN}/tables/{table_id}/fields",
                    headers=headers,
                    json={"field_name": k, "type": f_type},
                    timeout=10,
                ).json()
                if c_res.get("code") == 0:
                    col_types[k] = f_type
            except Exception:
                pass

        t = col_types.get(k, 1)
        if t == 2:
            try:
                clean_fields[k] = float(v)
            except Exception:
                clean_fields[k] = 0.0
        else:
            if isinstance(v, (list, dict)):
                clean_fields[k] = ", ".join(str(x) for x in v) if isinstance(v, list) else str(v)
            else:
                clean_fields[k] = str(v)
    return clean_fields


def add_record(table_id, fields_dict):
    headers = _get_headers()
    if not headers or not config.FEISHU_APP_TOKEN or not table_id:
        return {"code": -1, "msg": "飞书未配置"}
    try:
        safe_fields = _prepare_fields(table_id, fields_dict, headers)
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{config.FEISHU_APP_TOKEN}/tables/{table_id}/records"
        return requests.post(
            url, headers=headers, json={"fields": safe_fields}, timeout=15
        ).json()
    except Exception as e:
        return {"code": -1, "msg": str(e)}


def update_record(table_id, record_id, fields_dict):
    headers = _get_headers()
    if not headers or not config.FEISHU_APP_TOKEN or not table_id:
        return {"code": -1, "msg": "飞书未配置"}
    try:
        safe_fields = _prepare_fields(table_id, fields_dict, headers)
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{config.FEISHU_APP_TOKEN}/tables/{table_id}/records/{record_id}"
        return requests.put(
            url, headers=headers, json={"fields": safe_fields}, timeout=15
        ).json()
    except Exception as e:
        return {"code": -1, "msg": str(e)}


def _extract_val(val):
    if isinstance(val, list):
        return ", ".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in val)
    return val


class FeishuDB:
    """V5.0 飞书多维表格客户端封装类"""

    def __init__(self):
        headers = _get_headers()
        self.token = _TOKEN_CACHE.get("token", "") if headers else ""

    def get_strategy_weights(self):
        default_weights = {
            "track_heat": 0.25,
            "price_safety": 0.25,
            "tech_strength": 0.20,
            "marketing_vc": 0.15,
            "mc_odds": 0.15,
        }
        if not self.token or not config.TABLE_ID_CONFIG:
            return default_weights

        records = get_records(config.TABLE_ID_CONFIG)
        if not records:
            return default_weights

        fields = records[0].get("fields", {})
        try:
            w_track = float(_extract_val(fields.get("赛道热度权重", 25)) or 25)
            w_safety = float(_extract_val(fields.get("价格安全权重", 25)) or 25)
            w_tech = float(_extract_val(fields.get("技术实力权重", 20)) or 20)
            w_vc = float(_extract_val(fields.get("营销背书权重", 15)) or 15)
            w_mc = float(_extract_val(fields.get("市值赔率权重", 15)) or 15)
            total = w_track + w_safety + w_tech + w_vc + w_mc
            if total <= 0:
                return default_weights
            return {
                "track_heat": round(w_track / total, 4),
                "price_safety": round(w_safety / total, 4),
                "tech_strength": round(w_tech / total, 4),
                "marketing_vc": round(w_vc / total, 4),
                "mc_odds": round(w_mc / total, 4),
            }
        except Exception:
            return default_weights

    def get_approved_tracks(self):
        if not self.token or not config.TABLE_ID_RADAR:
            return []
        records = get_records(config.TABLE_ID_RADAR)
        tracks = []
        seen_ids = set()
        for r in records:
            f = r.get("fields", {})
            t_id = str(_extract_val(f.get("赛道ID") or f.get("id") or "")).strip()
            t_name = str(_extract_val(f.get("赛道名称") or f.get("name") or t_id)).strip()
            status = str(_extract_val(f.get("人工状态") or f.get("status") or "允许深挖")).strip()
            if not t_id or t_id in seen_ids:
                continue
            if any(bad in status for bad in ["拒绝", "忽略", "屏蔽", "禁止"]):
                continue
            try:
                chg = float(str(_extract_val(f.get("24h涨幅(%)") or f.get("change_24h") or 0)).replace("%", ""))
            except Exception:
                chg = 0.0
            seen_ids.add(t_id)
            tracks.append({
                "id": t_id,
                "name": t_name,
                "source": str(_extract_val(f.get("发现来源") or f.get("source") or "🔥赛道强势反弹")),
                "change_24h": chg,
                "reason": str(_extract_val(f.get("AI赛道简评") or f.get("reason") or "")),
                "status": status,
            })
        return tracks

    def save_alpha_project(self, p_data):
        if not self.token or not config.TABLE_ID_ALPHA:
            return {"code": -1, "msg": "飞书未配置"}
        fields = {
            "项目ID": str(p_data.get("coingecko_id") or p_data.get("id") or ""),
            "代币符号": str(p_data.get("symbol", "")),
            "项目名称": str(p_data.get("name", "")),
            "公链": str(p_data.get("chain", "MULTI")),
            "合约地址": str(p_data.get("contract_address", "")),
            "机会类型": str(p_data.get("opp_type", "")),
            "所属赛道": str(p_data.get("track", "")),
            "核心催化剂": str(p_data.get("catalyst", "")),
            "推荐时价格": float(p_data.get("price") or 0.0),
            "24h涨幅(%)": float(p_data.get("change_24h") or 0.0),
            "24h换手率(%)": float(p_data.get("turnover_24h") or 0.0),
            "流通市值(万)": float(p_data.get("market_cap") or 0.0),
            "DEX流动性(万)": float(p_data.get("liquidity_wan") or 0.0),
            "流通率MC/FDV(%)": float(p_data.get("mc_fdv_ratio") or 0.0),
            "距高点跌幅(%)": float(p_data.get("ath_drop") or 0.0),
            "综合总分": float(p_data.get("final_score") or 0.0),
            "AI投委会研报": str(p_data.get("ai_report", "")),
            "看线链接": str(p_data.get("dex_url", "")),
            "发现时间": str(p_data.get("discovered_at", "")),
        }
        return add_record(config.TABLE_ID_ALPHA, fields)
