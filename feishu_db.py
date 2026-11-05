# feishu_db.py
import config
import requests


def _get_headers():
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
  )
  token = res.json().get("tenant_access_token")
  return {
      "Authorization": f"Bearer {token}",
      "Content-Type": "application/json",
  }


def get_records(table_id):
  """读取指定表格的所有记录"""
  url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{config.FEISHU_APP_TOKEN}/tables/{table_id}/records?page_size=100"
  res = requests.get(url, headers=_get_headers(), timeout=15).json()
  return res.get("data", {}).get("items", [])


def add_record(table_id, fields_dict):
  """向指定表格新增一行"""
  url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{config.FEISHU_APP_TOKEN}/tables/{table_id}/records"
  res = requests.post(
      url,
      headers=_get_headers(),
      json={"fields": fields_dict},
      timeout=15,
  )
  return res.json()


def update_record(table_id, record_id, fields_dict):
  """更新指定行的内容"""
  url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{config.FEISHU_APP_TOKEN}/tables/{table_id}/records/{record_id}"
  res = requests.put(
      url,
      headers=_get_headers(),
      json={"fields": fields_dict},
      timeout=15,
  )
  return res.json()