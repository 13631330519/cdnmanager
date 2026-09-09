import datetime
import hashlib
import hmac
import json
from urllib.parse import quote

import requests

from common import log

VOLCENGINE_CDN_HOST = 'cdn.volcengineapi.com'
VOLCENGINE_CDN_SERVICE = 'cdn'
VOLCENGINE_CDN_REGION = 'cn-north-1'
VOLCENGINE_CDN_VERSION = '2021-03-01'
VOLCENGINE_CONTENT_TYPE = 'application/json'


def _utc_now():
    try:
        from datetime import timezone
        return datetime.datetime.now(timezone.utc)
    except ImportError:
        return datetime.datetime.utcnow()


def _norm_query(params):
    query = ''
    for key in sorted(params.keys()):
        value = params[key]
        if isinstance(value, list):
            for item in value:
                query += quote(key, safe='-_.~') + '=' + quote(str(item), safe='-_.~') + '&'
        else:
            query += quote(key, safe='-_.~') + '=' + quote(str(value), safe='-_.~') + '&'
    query = query[:-1]
    return query.replace('+', '%20')


def _hash_sha256(content):
    if content is None:
        content = ''
    if isinstance(content, bytes):
        return hashlib.sha256(content).hexdigest()
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def _hmac_sha256(key, content):
    if isinstance(key, str):
        key = key.encode('utf-8')
    if isinstance(content, str):
        content = content.encode('utf-8')
    return hmac.new(key, content, hashlib.sha256).digest()


def _build_auth_headers(access_key, secret_key, method, query, body):
    body_str = body if body is not None else ''
    x_date = _utc_now().strftime('%Y%m%dT%H%M%SZ')
    short_x_date = x_date[:8]
    payload_hash = _hash_sha256(body_str)
    signed_headers = 'content-type;host;x-content-sha256;x-date'
    canonical_request = '\n'.join([
        method.upper(),
        '/',
        _norm_query(query),
        '\n'.join([
            'content-type:' + VOLCENGINE_CONTENT_TYPE,
            'host:' + VOLCENGINE_CDN_HOST,
            'x-content-sha256:' + payload_hash,
            'x-date:' + x_date,
        ]),
        '',
        signed_headers,
        payload_hash,
    ])
    credential_scope = '/'.join([short_x_date, VOLCENGINE_CDN_REGION, VOLCENGINE_CDN_SERVICE, 'request'])
    string_to_sign = '\n'.join([
        'HMAC-SHA256',
        x_date,
        credential_scope,
        _hash_sha256(canonical_request),
    ])
    k_date = _hmac_sha256(secret_key, short_x_date)
    k_region = _hmac_sha256(k_date, VOLCENGINE_CDN_REGION)
    k_service = _hmac_sha256(k_region, VOLCENGINE_CDN_SERVICE)
    k_signing = _hmac_sha256(k_service, 'request')
    signature = _hmac_sha256(k_signing, string_to_sign).hex()
    authorization = (
        f'HMAC-SHA256 Credential={access_key}/{credential_scope}, '
        f'SignedHeaders={signed_headers}, Signature={signature}'
    )
    return {
        'Host': VOLCENGINE_CDN_HOST,
        'Content-Type': VOLCENGINE_CONTENT_TYPE,
        'X-Date': x_date,
        'X-Content-Sha256': payload_hash,
        'Authorization': authorization,
    }


def _volcengine_request(action, credentials, body=None):
    access_key = credentials.get('access_key')
    secret_key = credentials.get('secret_key')
    if not access_key or not secret_key:
        return {'success': False, 'message': '火山云凭据不完整，需填写 AccessKey 和 SecretKey'}

    query = {'Action': action, 'Version': VOLCENGINE_CDN_VERSION}
    body_str = json.dumps(body, separators=(',', ':'), ensure_ascii=False) if body is not None else ''
    headers = _build_auth_headers(access_key, secret_key, 'POST', query, body_str)
    url = f'https://{VOLCENGINE_CDN_HOST}/?{_norm_query(query)}'

    try:
        response = requests.post(url, headers=headers, data=body_str.encode('utf-8'), timeout=30)
        data = response.json()
        log({'provider': 'volcengine', 'action': action, 'response': data})
        if response.status_code != 200:
            return {'success': False, 'message': f'火山云 CDN 请求失败: HTTP {response.status_code}', 'response': data}

        error = (data.get('ResponseMetadata') or {}).get('Error')
        if error:
            message = error.get('Message') if isinstance(error, dict) else str(error)
            return {'success': False, 'message': message or '火山云 CDN 请求失败', 'response': data}
        return {'success': True, 'response': data}
    except Exception as exc:
        return {'success': False, 'message': f'火山云 CDN 请求异常: {exc}'}


def refresh_volcengine(domain, credentials, url=None):
    if not credentials.get('access_key') or not credentials.get('secret_key'):
        return {'success': False, 'message': '请先配置火山云 AccessKey 和 SecretKey', 'provider': 'volcengine'}

    if url and not url.endswith('/'):
        refresh_type = 'file'
        task_type = 'refresh_file'
        url_list = [url]
    else:
        refresh_type = 'dir'
        task_type = 'refresh_dir'
        url_list = [url] if url else [f'https://{domain}/', f'http://{domain}/']

    result = _volcengine_request(
        'SubmitRefreshTask',
        credentials,
        body={'Type': refresh_type, 'UrlList': url_list},
    )
    if not result.get('success'):
        return {'success': False, 'message': result.get('message'), 'provider': 'volcengine'}

    task_id = (result.get('response') or {}).get('Result', {}).get('TaskID')
    if not task_id:
        return {'success': False, 'message': '火山云刷新请求提交成功，但未返回任务ID', 'provider': 'volcengine'}

    return {
        'success': True,
        'message': f'火山云刷新请求已提交: {url or domain}, 任务ID={task_id}',
        'provider': 'volcengine',
        'task_id': str(task_id),
        'refresh_status': '正在刷新',
        'refresh_task_detail': {'task_type': task_type},
    }


def check_volcengine_task(task_id, credentials, refresh_task_detail=None):
    task_types = []
    if refresh_task_detail and refresh_task_detail.get('task_type'):
        task_types.append(refresh_task_detail['task_type'])
    task_types.extend(['refresh_file', 'refresh_dir'])

    seen = set()
    last_error = None
    for task_type in task_types:
        if task_type in seen:
            continue
        seen.add(task_type)

        result = _volcengine_request(
            'DescribeContentTasks',
            credentials,
            body={'TaskID': task_id, 'TaskType': task_type, 'PageNum': 1, 'PageSize': 50},
        )
        if not result.get('success'):
            last_error = result.get('message')
            continue

        tasks = (result.get('response') or {}).get('Result', {}).get('Data') or []
        if not tasks:
            continue

        statuses = [(item.get('Status') or '').lower() for item in tasks]
        if any(status == 'failed' for status in statuses):
            task_status = 'failed'
        elif all(status == 'complete' for status in statuses):
            task_status = 'complete'
        else:
            task_status = 'running'

        return {
            'success': True,
            'provider': 'volcengine',
            'task_status': task_status,
            'status_detail': tasks,
        }

    return {
        'success': False,
        'message': last_error or '未找到火山云刷新任务',
        'provider': 'volcengine',
    }
