import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone

import requests

from common import log

CTYUN_CDN_ENDPOINT = 'https://cdnapi-global.ctapi.ctyun.cn'
CTYUN_SUCCESS_CODE = 10000


def _utc_eop_date():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def _sha256_hex(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(key, message):
    if isinstance(key, str):
        key = key.encode('utf-8')
    if isinstance(message, str):
        message = message.encode('utf-8')
    return hmac.new(key, message, hashlib.sha256).digest()


def _canonical_query(params):
    if not params:
        return ''
    return '&'.join(f'{key}={params[key]}' for key in sorted(params.keys()))


def _build_eop_authorization(access_key, secret_key, eop_date, request_id, query_string='', body=''):
    header_block = '\n'.join([
        f'ctyun-eop-request-id:{request_id}',
        f'eop-date:{eop_date}',
    ]) + '\n'
    body_hash = _sha256_hex(body or '')
    signature_string = f'{header_block}\n{query_string}\n{body_hash}'

    ktime = _hmac_sha256(secret_key, eop_date)
    kak = _hmac_sha256(ktime, access_key)
    kdate = _hmac_sha256(kak, eop_date[:8])
    signature = base64.b64encode(_hmac_sha256(kdate, signature_string)).decode('utf-8')
    return f'{access_key} Headers=ctyun-eop-request-id;eop-date Signature={signature}'


def _build_headers(access_key, secret_key, request_id, eop_date, query_string='', body=''):
    return {
        'Host': 'cdnapi-global.ctapi.ctyun.cn',
        'Content-Type': 'application/json;charset=UTF-8',
        'eop-date': eop_date,
        'ctyun-eop-request-id': request_id,
        'Eop-Authorization': _build_eop_authorization(
            access_key, secret_key, eop_date, request_id, query_string, body
        ),
    }


def _ctyun_request(method, path, credentials, body=None, query=None):
    access_key = credentials.get('access_key')
    secret_key = credentials.get('secret_key')
    if not access_key or not secret_key:
        return {'success': False, 'message': '天翼云凭据不完整，需填写 AccessKey 和 SecretKey'}

    query = query or {}
    query_string = _canonical_query(query)
    body_str = json.dumps(body, separators=(',', ':'), ensure_ascii=False) if body is not None else ''
    request_id = str(uuid.uuid4())
    eop_date = _utc_eop_date()
    headers = _build_headers(access_key, secret_key, request_id, eop_date, query_string, body_str)
    url = f'{CTYUN_CDN_ENDPOINT}{path}'
    if query_string:
        url = f'{url}?{query_string}'

    try:
        if method.upper() == 'GET':
            response = requests.get(url, headers=headers, timeout=30)
        else:
            response = requests.post(url, headers=headers, data=body_str, timeout=30)
        data = response.json()
        log({'provider': 'ctyun', 'path': path, 'query': query, 'response': data})
        if response.status_code != 200:
            return {'success': False, 'message': f'天翼云 CDN 请求失败: HTTP {response.status_code}', 'response': data}
        if data.get('code') != CTYUN_SUCCESS_CODE:
            return {
                'success': False,
                'message': data.get('message') or f'天翼云 CDN 请求失败(code={data.get("code")})',
                'response': data,
            }
        return {'success': True, 'response': data}
    except Exception as exc:
        return {'success': False, 'message': f'天翼云 CDN 请求异常: {exc}'}


def refresh_ctyun(domain, credentials, url=None):
    if not credentials.get('access_key') or not credentials.get('secret_key'):
        return {'success': False, 'message': '请先配置天翼云 AccessKey 和 SecretKey', 'provider': 'ctyun'}

    if url and not url.endswith('/'):
        task_type = 1
        values = [url]
    else:
        task_type = 2
        values = [url] if url else [f'https://{domain}/', f'http://{domain}/']

    result = _ctyun_request(
        'POST',
        '/refresh-task/create-refresh-task',
        credentials,
        body={'task_type': task_type, 'values': values},
    )
    if not result.get('success'):
        return {'success': False, 'message': result.get('message'), 'provider': 'ctyun'}

    data = result['response']
    submit_id = data.get('submit_id')
    task_results = data.get('result') or []
    task_id = submit_id or (task_results[0].get('task_id') if task_results else None)
    if not task_id:
        return {'success': False, 'message': '天翼云刷新请求提交成功，但未返回任务ID', 'provider': 'ctyun', 'response': data}

    return {
        'success': True,
        'message': f'天翼云刷新请求已提交: {url or domain}, 任务ID={task_id}',
        'provider': 'ctyun',
        'task_id': str(task_id),
        'refresh_status': '正在刷新',
        'refresh_task_detail': {
            'submit_id': submit_id,
            'task_ids': [item.get('task_id') for item in task_results if item.get('task_id')],
            'query_mode': 'submit_id' if submit_id else 'task_id',
        },
    }


def check_ctyun_task(task_id, credentials):
    query_modes = []
    if task_id:
        query_modes.append({'type': 1, 'submit_id': task_id})
        query_modes.append({'type': 2, 'task_id': task_id})

    last_error = None
    for query in query_modes:
        result = _ctyun_request('GET', '/refresh-task/query-refresh-task', credentials, query=query)
        if not result.get('success'):
            last_error = result.get('message')
            continue

        tasks = result['response'].get('result') or []
        if not tasks:
            continue

        statuses = [(item.get('status') or '').lower() for item in tasks]
        if any(status == 'failed' for status in statuses):
            task_status = 'failed'
        elif all(status == 'completed' for status in statuses):
            task_status = 'completed'
        else:
            task_status = 'processing'

        return {
            'success': True,
            'provider': 'ctyun',
            'task_status': task_status,
            'status_detail': tasks,
        }

    return {
        'success': False,
        'message': last_error or '未找到天翼云刷新任务',
        'provider': 'ctyun',
    }
