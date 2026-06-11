import hashlib
import json
from datetime import datetime
from common import log

import requests


def refresh_lingzhi(domain, credentials, url=None):
    if not credentials.get('access_key') or not credentials.get('secret_key'):
        return {"success": False, "message": "请先配置灵知 AccessKey 和 SecretKey", "provider": "lingzhi"}

    user_id = credentials.get('access_key')
    api_key = credentials.get('secret_key')
    if not user_id or not api_key:
        return {"success": False, "message": "灵知凭据不完整，需填写 userId 和 apiKey", "provider": "lingzhi"}

    urls = [url] if url else [f"https://{domain}/", f"http://{domain}/"]
    if url and not url.endswith('/'):
        refresh_type = "file"
    else:
        refresh_type = "dir"
    root = {
        "urls": urls,
        "type": refresh_type,
        "tc": int(datetime.now().timestamp())
    }
    root_json = json.dumps(root, separators=(",", ":"), ensure_ascii=False)
    sign_source = root_json + api_key
    sign = hashlib.md5(sign_source.encode('utf-8')).hexdigest()

    payload = {
        "userId": user_id,
        "root": root,
        "sign": sign
    }

    try:
        resp = requests.post("https://api.id-ai.cn/cdn/refresh_url/v1", json=payload, timeout=10)
        data = resp.json()
        if resp.status_code == 200 and data.get('code') == 0:
            return {"success": True, "message": f"灵知CDN刷新请求已提交: {domain}", "provider": "lingzhi"}
        log(data)
        return {"success": False, "message": data.get('desc') or f"灵知刷新失败，HTTP {resp.status_code}", "provider": "lingzhi"}
    except Exception as e:
        return {"success": False, "message": f"灵知刷新请求异常: {e}", "provider": "lingzhi"}
