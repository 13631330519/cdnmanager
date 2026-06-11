import json
import hashlib
import hmac
from datetime import datetime
from common import log

import requests

def sign_request(action, payload, secret_id, secret_key):
    timestamp = int(datetime.now().timestamp())
    date = datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d')
    payload_str = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False)

    http_request_method = "POST"
    canonical_uri = "/"
    canonical_querystring = ""
    canonical_headers = f"content-type:application/json; charset=utf-8\nhost:cdn.tencentcloudapi.com\n"
    signed_headers = "content-type;host"
    hashed_request_payload = hashlib.sha256(payload_str.encode('utf-8')).hexdigest()
    canonical_request = "\n".join([
        http_request_method,
        canonical_uri,
        canonical_querystring,
        canonical_headers,
        signed_headers,
        hashed_request_payload
    ])

    algorithm = "TC3-HMAC-SHA256"
    credential_scope = f"{date}/cdn/tc3_request"
    hashed_canonical_request = hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()
    string_to_sign = "\n".join([
        algorithm,
        str(timestamp),
        credential_scope,
        hashed_canonical_request
    ])

    secret_date = hmac.new(("TC3" + secret_key).encode('utf-8'), date.encode('utf-8'), hashlib.sha256).digest()
    secret_service = hmac.new(secret_date, b"cdn", hashlib.sha256).digest()
    secret_signing = hmac.new(secret_service, b"tc3_request", hashlib.sha256).digest()
    signature = hmac.new(secret_signing, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

    authorization = (
        f"{algorithm} Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    return {
        "Content-Type": "application/json; charset=utf-8",
        "Host": "cdn.tencentcloudapi.com",
        "Authorization": authorization,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": "2018-06-06",
        "X-TC-Region": "ap-guangzhou"
    }, payload_str

def refresh_tencentcdn(domain, credentials, url=None):
    if not credentials.get('access_key') or not credentials.get('secret_key'):
        return {"success": False, "message": "请先配置腾讯云 SecretId 和 SecretKey", "provider": "tencent"}

    secret_id = credentials.get('access_key')
    secret_key = credentials.get('secret_key')
    if not secret_id or not secret_key:
        return {"success": False, "message": "腾讯云凭据不完整，需填写 SecretId 和 SecretKey", "provider": "tencent"}

    urls = [url] if url else [f"https://{domain}/", f"http://{domain}/"]
    refresh_params = {
        "Urls": urls,
        "FlushType": "flush"
    } if url and not url.endswith('/') else{
        "Paths": urls,
        "FlushType": "flush"
    }

    endpoint = "https://cdn.tencentcloudapi.com"

    try:
        #刷新url还是目录
        action = "PurgeUrlsCache" if url and not url.endswith('/') else "PurgePathCache"
        headers, payload_str = sign_request(action, refresh_params, secret_id, secret_key)
        response = requests.post(endpoint, headers=headers, data=payload_str, timeout=10)

        refresh_data = response.json()
        log(refresh_data)
        if response.status_code != 200 or refresh_data.get('Response', {}).get('Error'):
            error_info = refresh_data.get('Response', {}).get('Error', {})
            msg = error_info.get('Message') if isinstance(error_info, dict) else str(error_info)
            return {"success": False, "message": f"腾讯云刷新失败: {msg}", "provider": "tencent"}

        task_id = refresh_data.get('Response', {}).get('TaskId')
        if not task_id:
            return {"success": False, "message": "腾讯云刷新请求提交成功，但未返回任务ID", "provider": "tencent"}

        return {
            "success": True,
            "message": f"腾讯云刷新请求已提交: {domain}, 任务ID={task_id}",
            "provider": "tencent",
            "task_id": task_id,
            "refresh_status": "正在刷新",
            "refresh_task_action": "DescribePurgeTasks"
        }
    except Exception as e:
        return {"success": False, "message": f"腾讯云刷新请求异常: {e}", "provider": "tencent"}


def check_tencent_task(task_id, credentials):
    endpoint = "https://cdn.tencentcloudapi.com"
    secret_id = credentials.get('access_key')
    secret_key = credentials.get('secret_key')

    query_action = "DescribePurgeTasks"
    headers, payload_str = sign_request(query_action, {"TaskId": task_id}, secret_id, secret_key)
    response = requests.post(endpoint, headers=headers, data=payload_str, timeout=10)
    data = response.json()
    log(data)
    if response.status_code != 200 or data.get('Response', {}).get('Error'):
        error_info = data.get('Response', {}).get('Error', {})
        msg = error_info.get('Message') if isinstance(error_info, dict) else str(error_info)
        return {"success": False, "message": f"查询腾讯云刷新任务失败: {msg}", "provider": "tencent"}
    tasks = data.get('Response', {}).get('PurgeLogs', [])
    if not tasks:
        return {"success": False, "message": "未找到腾讯云刷新任务", "provider": "tencent"}
    task = tasks[0]
    task_status = task.get('Status') or task.get('TaskStatus') or task.get('TaskState')
    return {
        "success": True,
        "provider": "tencent",
        "task_status": task_status,
        "status_detail": task
    }
