from common import log

AlidnsClient = None
alidns_models = None
open_api_models = None
TeaCore = None
_IMPORT_ERROR = None

try:
    from alibabacloud_alidns20150109.client import Client as AlidnsClient
    from alibabacloud_alidns20150109 import models as alidns_models
    from alibabacloud_tea_openapi import models as open_api_models
    from Tea.core import TeaCore
except ImportError as exc:
    _IMPORT_ERROR = exc


def _sdk_unavailable_message():
    detail = str(_IMPORT_ERROR) if _IMPORT_ERROR else '未知导入错误'
    return (
        f'阿里云 DNS SDK 未就绪: {detail}。'
        '请在服务虚拟环境中安装依赖，例如: '
        '/opt/cdnmanager/venv/bin/pip install -r /opt/cdnmanager/requirements.txt '
        '然后 systemctl restart cdnmanager'
    )


def _build_client(credentials):
    if AlidnsClient is None:
        raise RuntimeError(_sdk_unavailable_message())
    config = open_api_models.Config(
        access_key_id=credentials.get('access_key'),
        access_key_secret=credentials.get('secret_key'),
        endpoint='alidns.aliyuncs.com',
    )
    return AlidnsClient(config)


def _response_to_map(response):
    data = TeaCore.to_map(response)
    if isinstance(data, dict) and isinstance(data.get('body'), dict):
        return data['body']
    return data


def _normalize_aliyun_record(record):
    return {
        'record_id': str(record.get('RecordId')),
        'sub_domain': record.get('RR') or '',
        'record_type': record.get('Type') or '',
        'value': record.get('Value') or '',
        'ttl': record.get('TTL'),
        'line': record.get('Line') or 'default',
        'status': record.get('Status'),
        'mx': record.get('Priority'),
        'weight': record.get('Weight'),
    }


def list_dns_records_aliyun(root_domain, credentials, sub_domain=None, record_type=None):
    try:
        client = _build_client(credentials)
        request = alidns_models.DescribeDomainRecordsRequest(
            domain_name=root_domain,
            rrkey_word=sub_domain,
            type=record_type,
            page_size=500,
        )
        response = client.describe_domain_records(request)
        data = _response_to_map(response)
        log({'provider': 'dns_aliyun', 'action': 'DescribeDomainRecords', 'response': data})
        records = data.get('DomainRecords', {}).get('Record') or []
        if isinstance(records, dict):
            records = [records]
        normalized = [_normalize_aliyun_record(item) for item in records]
        return {'success': True, 'records': normalized, 'provider': 'aliyun'}
    except Exception as exc:
        return {'success': False, 'message': f'阿里云 DNS 查询失败: {exc}'}


def update_dns_record_aliyun(root_domain, credentials, record_id, sub_domain, record_type, value, ttl=None, line=None):
    try:
        client = _build_client(credentials)
        request = alidns_models.UpdateDomainRecordRequest(
            record_id=record_id,
            rr=sub_domain,
            type=record_type,
            value=value,
            ttl=int(ttl or 600),
            line=line or 'default',
        )
        response = client.update_domain_record(request)
        data = _response_to_map(response)
        log({'provider': 'dns_aliyun', 'action': 'UpdateDomainRecord', 'response': data})
        return {'success': True, 'message': 'DNS 记录已更新', 'provider': 'aliyun', 'record_id': str(record_id)}
    except Exception as exc:
        return {'success': False, 'message': f'阿里云 DNS 更新失败: {exc}'}


def create_dns_record_aliyun(root_domain, credentials, sub_domain, record_type, value, ttl=600, line=None):
    try:
        client = _build_client(credentials)
        request = alidns_models.AddDomainRecordRequest(
            domain_name=root_domain,
            rr=sub_domain,
            type=record_type,
            value=value,
            ttl=int(ttl or 600),
            line=line or 'default',
        )
        response = client.add_domain_record(request)
        data = _response_to_map(response)
        log({'provider': 'dns_aliyun', 'action': 'AddDomainRecord', 'response': data})
        record_id = data.get('RecordId')
        return {'success': True, 'message': 'DNS 记录已创建', 'provider': 'aliyun', 'record_id': str(record_id)}
    except Exception as exc:
        return {'success': False, 'message': f'阿里云 DNS 创建失败: {exc}'}


def delete_dns_record_aliyun(root_domain, credentials, record_id):
    try:
        client = _build_client(credentials)
        request = alidns_models.DeleteDomainRecordRequest(record_id=record_id)
        response = client.delete_domain_record(request)
        data = _response_to_map(response)
        log({'provider': 'dns_aliyun', 'action': 'DeleteDomainRecord', 'response': data})
        return {'success': True, 'message': 'DNS 记录已删除', 'provider': 'aliyun'}
    except Exception as exc:
        return {'success': False, 'message': f'阿里云 DNS 删除失败: {exc}'}
