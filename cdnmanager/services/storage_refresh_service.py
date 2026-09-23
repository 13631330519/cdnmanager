"""Resolve CDN domains from storage target project/env and refresh uploaded files."""

import cdnmanager.db as db
import cdnmanager.services.refresh_service as refresh_service


def build_cdn_file_url(domain_name, storage_key):
    domain_name = (domain_name or '').strip()
    if not domain_name:
        return None
    key = (storage_key or '').lstrip('/')
    return f'https://{domain_name}/{key}'


def build_cdn_file_urls(domain_name, storage_key):
    base_url = build_cdn_file_url(domain_name, storage_key)
    if not base_url:
        return []
    return [base_url, base_url.replace('https://', 'http://', 1)]


def find_domains_for_storage_target(target):
    environment_id = target.get('environment_id')
    project_id = target.get('project_id')
    if not environment_id:
        return []

    domains = []
    for domain in db.load_domains():
        if domain.get('environment_id') != environment_id:
            continue
        if project_id and domain.get('project_id') != project_id:
            continue
        domains.append(domain)
    return domains


def refresh_file_for_target(target, storage_key):
    domains = find_domains_for_storage_target(target)
    if not domains:
        return {
            'success': False,
            'error': '未找到绑定该项目/环境的 CDN 域名',
            'refreshed': 0,
            'results': [],
        }

    results = []
    refreshed = failed = 0
    for domain_record in domains:
        urls = build_cdn_file_urls(domain_record['domain'], storage_key)
        credential = db.get_credential(domain_record.get('provider'), domain_record.get('credential_id'))
        if not credential:
            failed += 1
            results.append({
                'domain': domain_record['domain'],
                'success': False,
                'error': 'CDN 凭据不存在',
            })
            continue

        for url in urls:
            result = refresh_service.refresh_and_record(domain_record, credential, url=url, record_url=True)
            entry = {
                'domain': domain_record['domain'],
                'url': url,
                'success': bool(result.get('success')),
                'result': result,
            }
            results.append(entry)
            if result.get('success'):
                refreshed += 1
            else:
                failed += 1

    return {
        'success': refreshed > 0,
        'refreshed': refreshed,
        'failed': failed,
        'results': results,
        'error': None if refreshed else (results[0].get('result', {}).get('error') if results else '刷新失败'),
    }
