# feishu_db.py - V4.0 自愈版（自动创建飞书缺失列 + 类型自适应）
import config
import requests


def _get_headers():
  if not config.FEISHU_APP_ID or not config.FEISHU_APP_SECRET:
    return None
  url = (
      "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
  )
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
  return {
      "Authorization": f"Bearer {token}",
      "Content-Type": "application/json",
  }


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
  url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{config.FEISHU_APP_TOKEN}/tables/{table_id}/fields?page_size=100"
  res = requests.get(url, headers=headers, timeout=15).json()
  items = res.get("data", {}).get("items", []) or []
  col_types = {i["field_name"]: i["type"] for i in items}

  clean_fields = {}
  for k, v in fields_dict.items():
    if k not in col_types:
      f_type = 2 if isinstance(v, (int, float)) else 1
      c_res = requests.post(
          f"https://open.feishu.cn/open-apis/bitable/v1/apps/{config.FEISHU_APP_TOKEN}/tables/{table_id}/fields",
          headers=headers,
          json={"field_name": k, "type": f_type},
          timeout=10,
      ).json()
      if c_res.get("code") == 0:
        col_types[k] = f_type
    t = col_types.get(k, 1)
    if t == 2:
      try:
        clean_fields[k] = float(v)
      except Exception:
        clean_fields[k] = 0.0
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
