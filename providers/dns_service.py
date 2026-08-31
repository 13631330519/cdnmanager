from providers.dns_aliyun import (
    list_dns_records_aliyun,
    update_dns_record_aliyun,
    create_dns_record_aliyun,
    delete_dns_record_aliyun,
)
from providers.dns_tencent import (
    list_dns_records_tencent,
    update_dns_record_tencent,
    create_dns_record_tencent,
    delete_dns_record_tencent,
)


def list_dns_records(root_domain, dns_provider, credentials, sub_domain=None, record_type=None):
    if dns_provider == 'aliyun':
        return list_dns_records_aliyun(root_domain, credentials, sub_domain, record_type)
    if dns_provider == 'tencent':
        return list_dns_records_tencent(root_domain, credentials, sub_domain, record_type)
    return {'success': False, 'message': f'不支持的 DNS 服务商: {dns_provider}'}


def update_dns_record(root_domain, dns_provider, credentials, record_id, sub_domain, record_type, value, ttl=None, line=None):
    if dns_provider == 'aliyun':
        return update_dns_record_aliyun(root_domain, credentials, record_id, sub_domain, record_type, value, ttl, line)
    if dns_provider == 'tencent':
        return update_dns_record_tencent(root_domain, credentials, record_id, sub_domain, record_type, value, ttl, line)
    return {'success': False, 'message': f'不支持的 DNS 服务商: {dns_provider}'}


def create_dns_record(root_domain, dns_provider, credentials, sub_domain, record_type, value, ttl=600, line=None):
    if dns_provider == 'aliyun':
        return create_dns_record_aliyun(root_domain, credentials, sub_domain, record_type, value, ttl, line)
    if dns_provider == 'tencent':
        return create_dns_record_tencent(root_domain, credentials, sub_domain, record_type, value, ttl, line)
    return {'success': False, 'message': f'不支持的 DNS 服务商: {dns_provider}'}


def delete_dns_record(root_domain, dns_provider, credentials, record_id):
    if dns_provider == 'aliyun':
        return delete_dns_record_aliyun(root_domain, credentials, record_id)
    if dns_provider == 'tencent':
        return delete_dns_record_tencent(root_domain, credentials, record_id)
    return {'success': False, 'message': f'不支持的 DNS 服务商: {dns_provider}'}
