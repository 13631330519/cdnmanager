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


def collapse_storage_keys_to_highest_dirs(storage_keys):
    """Collapse uploaded object keys into the highest directory prefixes to refresh.

    Directory keys end with '/'. Root-level files stay as file keys.
    Examples:
      a/b/1.txt, a/c/2.txt  -> ['a/']
      a/1.txt, b/2.txt      -> ['a/', 'b/']
      only.txt              -> ['only.txt']
    """
    dir_parts_list = []
    root_files = []
    for raw in storage_keys or []:
        key = (raw or '').replace('\\', '/').strip('/')
        if not key:
            continue
        parts = [part for part in key.split('/') if part]
        if not parts:
            continue
        if len(parts) == 1:
            root_files.append(parts[0])
            continue
        dir_parts_list.append(parts[:-1])

    if not dir_parts_list:
        return list(dict.fromkeys(root_files))

    common = list(dir_parts_list[0])
    for parts in dir_parts_list[1:]:
        limit = min(len(common), len(parts))
        index = 0
        while index < limit and common[index] == parts[index]:
            index += 1
        common = common[:index]
        if not common:
            break

    if common:
        dirs = ['/'.join(common) + '/']
    else:
        dirs = sorted({f'{parts[0]}/' for parts in dir_parts_list})

    return list(dict.fromkeys([*dirs, *root_files]))


def refresh_files_for_target(target, storage_keys, collapse_dirs=False):
    """Refresh keys on each bound domain with one CDN request per domain.

    When collapse_dirs=True, file keys are folded into highest directory prefixes
    (URL ends with '/') so CDN uses directory refresh instead of per-file purge.
    """
    raw_keys = [key for key in (storage_keys or []) if key]
    keys = collapse_storage_keys_to_highest_dirs(raw_keys) if collapse_dirs else raw_keys
    domains = find_domains_for_storage_target(target)
    if not domains:
        return {
            'success': False,
            'error': '未找到绑定该项目/环境的 CDN 域名',
            'refreshed': 0,
            'results': [],
        }
    if not keys:
        return {'success': True, 'refreshed': 0, 'failed': 0, 'results': [], 'skipped': True}

    results = []
    refreshed = failed = 0
    for domain_record in domains:
        urls = []
        for storage_key in keys:
            urls.extend(build_cdn_file_urls(domain_record['domain'], storage_key))
        credential = db.get_credential(domain_record.get('provider'), domain_record.get('credential_id'))
        if not credential:
            failed += 1
            results.append({
                'domain': domain_record['domain'],
                'urls': urls,
                'success': False,
                'error': 'CDN 凭据不存在',
            })
            continue

        result = refresh_service.refresh_and_record(
            domain_record, credential, urls=urls, record_url=True,
        )
        entry = {
            'domain': domain_record['domain'],
            'url': urls[0] if urls else None,
            'urls': urls,
            'url_count': len(urls),
            'success': bool(result.get('success')),
            'result': result,
            'refresh_paths': keys,
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
        'file_count': len(raw_keys),
        'path_count': len(keys),
        'refresh_paths': keys,
        'collapsed': bool(collapse_dirs),
        'results': results,
        'error': None if refreshed else (
            ((results[0].get('result') or {}).get('error') or results[0].get('error') or '刷新失败')
            if results else '刷新失败'
        ),
    }
