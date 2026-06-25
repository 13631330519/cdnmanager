
import requests
from datetime import datetime, timedelta
from akamai.edgegrid import EdgeGridAuth

from common import log, REFRESH_STATUS_REFRESHING, REFRESH_STATUS_COMPLETE

DEFAULT_AKAMAI_API_HOST = 'https://akab-bvrty4llf7emi3cx-q5b27ednbqdbnoha.luna.akamaiapis.net'


def _parse_akamai_credentials(credentials):
    client_token = (credentials.get('extra_key') or '').strip()
    client_secret = (credentials.get('secret_key') or '').strip()
    access_token = (credentials.get('access_key') or '').strip()
    api_host = (credentials.get('extra_secret') or '').strip() or DEFAULT_AKAMAI_API_HOST

    if not client_token and access_token.startswith('akab-'):
        client_token = access_token
        access_token = ''

    if api_host and not api_host.startswith('http'):
        api_host = f'https://{api_host}'

    return client_token, client_secret, access_token, api_host.rstrip('/')


def _build_refresh_detail(data, task_id):
    estimated_seconds = data.get('estimatedSeconds')
    if estimated_seconds is None:
        estimated_seconds = 0
    return {
        'purge_id': task_id,
        'estimated_seconds': int(estimated_seconds),
        'submitted_at': datetime.now().isoformat(),
        'estimatedSeconds': int(estimated_seconds),
    }


def check_akamai_refresh(refresh_task_detail):
    if not refresh_task_detail or not isinstance(refresh_task_detail, dict):
        return {"success": False, "message": "无 Akamai 刷新详情", "provider": "akamai"}

    submitted_at = refresh_task_detail.get('submitted_at')
    estimated_seconds = refresh_task_detail.get('estimated_seconds', refresh_task_detail.get('estimatedSeconds', 0))
    if not submitted_at:
        return {"success": False, "message": "缺少 Akamai 刷新提交时间", "provider": "akamai"}

    try:
        estimated_seconds = int(estimated_seconds)
    except (TypeError, ValueError):
        estimated_seconds = 0

    submitted = datetime.fromisoformat(submitted_at)
    complete_at = submitted + timedelta(seconds=estimated_seconds)
    if datetime.now() >= complete_at:
        return {
            "success": True,
            "provider": "akamai",
            "task_status": "complete",
            "status_detail": refresh_task_detail,
        }

    return {
        "success": True,
        "provider": "akamai",
        "task_status": "refreshing",
        "status_detail": refresh_task_detail,
    }


def refresh_akamai(domain, credentials, url=None, cpcode=None):
    client_token, client_secret, access_token, api_host = _parse_akamai_credentials(credentials)
    if not client_token or not client_secret or not access_token:
        return {
            "success": False,
            "message": "Akamai 凭据不完整，需填写 Client Token、Client Secret、Access Token 和 API Host",
            "provider": "akamai",
        }

    if url:
        api_endpoint = f'{api_host}/ccu/v3/invalidate/url/production'
        payload = {'objects': [url]}
        purge_target = url
    else:
        if not cpcode:
            return {
                "success": False,
                "message": f"域名 {domain} 未配置 CP Code，请在域名设置中填写",
                "provider": "akamai",
            }
        api_endpoint = f'{api_host}/ccu/v3/invalidate/cpcode/production'
        payload = {'objects': [str(cpcode)]}
        purge_target = f'cpcode:{cpcode}'

    try:
        auth = EdgeGridAuth(
            client_token=client_token,
            client_secret=client_secret,
            access_token=access_token,
        )
        headers = {'Content-Type': 'application/json'}
        response = requests.post(api_endpoint, json=payload, auth=auth, headers=headers, timeout=30)

        if response.status_code == 201:
            data = response.json() if response.content else {}
            task_id = data.get('purgeId') or data.get('supportId')
            refresh_detail = _build_refresh_detail(data, task_id)
            return {
                "success": True,
                "message": f"Akamai CDN刷新请求已提交: {purge_target}",
                "provider": "akamai",
                "task_id": task_id,
                "refresh_task_detail": refresh_detail,
                "refresh_status": REFRESH_STATUS_REFRESHING if task_id else REFRESH_STATUS_COMPLETE,
            }

        log({"provider": "akamai", "status_code": response.status_code, "body": response.text})
        return {"success": False, "message": f"Akamai CDN刷新请求失败: {purge_target}", "provider": "akamai"}

    except Exception as e:
        log({"provider": "akamai", "error": str(e)})
        return {"success": False, "message": f"Akamai CDN刷新请求失败: {purge_target}", "provider": "akamai"}
