import json
import hashlib
import hmac
from datetime import datetime

import requests

from common import log


def sign_dnspod_request(action, payload, secret_id, secret_key):
    timestamp = int(datetime.now().timestamp())
    date = datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d')
    payload_str = json.dumps(payload, separators=(',', ':'), sort_keys=True, ensure_ascii=False)

    canonical_headers = 'content-type:application/json; charset=utf-8\nhost:dnspod.tencentcloudapi.com\n'
    signed_headers = 'content-type;host'
    hashed_request_payload = hashlib.sha256(payload_str.encode('utf-8')).hexdigest()
    canonical_request = '\n'.join([
        'POST',
        '/',
        '',
        canonical_headers,
        signed_headers,
        hashed_request_payload,
    ])

    credential_scope = f'{date}/dnspod/tc3_request'
    hashed_canonical_request = hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()
    string_to_sign = '\n'.join([
        'TC3-HMAC-SHA256',
        str(timestamp),
        credential_scope,
        hashed_canonical_request,
    ])

    secret_date = hmac.new(('TC3' + secret_key).encode('utf-8'), date.encode('utf-8'), hashlib.sha256).digest()
    secret_service = hmac.new(secret_date, b'dnspod', hashlib.sha256).digest()
    secret_signing = hmac.new(secret_service, b'tc3_request', hashlib.sha256).digest()
    signature = hmac.new(secret_signing, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

    headers = {
        'Content-Type': 'application/json; charset=utf-8',
        'Host': 'dnspod.tencentcloudapi.com',
        'Authorization': (
            f'TC3-HMAC-SHA256 Credential={secret_id}/{credential_scope}, '
            f'SignedHeaders={signed_headers}, Signature={signature}'
        ),
        'X-TC-Action': action,
        'X-TC-Timestamp': str(timestamp),
        'X-TC-Version': '2021-03-23',
    }
    return headers, payload_str


def _tencent_request(action, payload, credentials):
    secret_id = credentials.get('access_key')
    secret_key = credentials.get('secret_key')
    headers, payload_str = sign_dnspod_request(action, payload, secret_id, secret_key)
    response = requests.post(
        'https://dnspod.tencentcloudapi.com',
        headers=headers,
        data=payload_str,
        timeout=30,
    )
    data = response.json()
    log({'provider': 'dns_tencent', 'action': action, 'response': data})
    if response.status_code != 200 or data.get('Response', {}).get('Error'):
        error_info = data.get('Response', {}).get('Error', {})
        msg = error_info.get('Message') if isinstance(error_info, dict) else str(error_info)
        return {'success': False, 'message': msg or '腾讯云 DNS 请求失败'}
    return {'success': True, 'response': data.get('Response', {})}


def _normalize_tencent_record(record):
    return {
        'record_id': str(record.get('RecordId')),
        'sub_domain': record.get('SubDomain') or record.get('Name') or '',
        'record_type': record.get('RecordType') or record.get('Type') or '',
        'value': record.get('Value') or '',
        'ttl': record.get('TTL'),
        'line': record.get('Line') or record.get('RecordLine') or '默认',
        'status': record.get('Status'),
        'mx': record.get('MX'),
        'weight': record.get('Weight'),
    }


def list_dns_records_tencent(root_domain, credentials, sub_domain=None, record_type=None):
    payload = {'Domain': root_domain, 'Limit': 3000}
    if sub_domain:
        payload['Subdomain'] = sub_domain
    if record_type:
        payload['RecordType'] = record_type

    result = _tencent_request('DescribeRecordList', payload, credentials)
    if not result.get('success'):
        return result

    records = result['response'].get('RecordList') or []
    normalized = [_normalize_tencent_record(item) for item in records]
    return {'success': True, 'records': normalized, 'provider': 'tencent'}


def update_dns_record_tencent(root_domain, credentials, record_id, sub_domain, record_type, value, ttl=None, line=None):
    payload = {
        'Domain': root_domain,
        'RecordId': int(record_id),
        'SubDomain': sub_domain,
        'RecordType': record_type,
        'RecordLine': line or '默认',
        'Value': value,
    }
    if ttl is not None:
        payload['TTL'] = int(ttl)

    result = _tencent_request('ModifyRecord', payload, credentials)
    if not result.get('success'):
        return result
    return {'success': True, 'message': 'DNS 记录已更新', 'provider': 'tencent', 'record_id': str(record_id)}


def create_dns_record_tencent(root_domain, credentials, sub_domain, record_type, value, ttl=600, line=None):
    payload = {
        'Domain': root_domain,
        'SubDomain': sub_domain,
        'RecordType': record_type,
        'RecordLine': line or '默认',
        'Value': value,
        'TTL': int(ttl or 600),
    }
    result = _tencent_request('CreateRecord', payload, credentials)
    if not result.get('success'):
        return result
    record_id = result['response'].get('RecordId')
    return {'success': True, 'message': 'DNS 记录已创建', 'provider': 'tencent', 'record_id': str(record_id)}


def delete_dns_record_tencent(root_domain, credentials, record_id):
    payload = {'Domain': root_domain, 'RecordId': int(record_id)}
    result = _tencent_request('DeleteRecord', payload, credentials)
    if not result.get('success'):
        return result
    return {'success': True, 'message': 'DNS 记录已删除', 'provider': 'tencent'}
