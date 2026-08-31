from common import CDN_CNAME_SUFFIXES, KNOWN_CDN_CNAME_SUFFIXES, log
from models import load_root_domains, get_dns_credential
from providers.dns_service import list_dns_records, update_dns_record


def _normalize_host(value):
    return (value or '').rstrip('.').lower()


def _extract_cname_prefix(value):
    host = _normalize_host(value)
    for suffix in KNOWN_CDN_CNAME_SUFFIXES:
        marker = f'.{suffix}'
        if host.endswith(marker):
            prefix = host[:-len(marker)]
            return prefix or None
    return None


def _build_cname_value(prefix, cdn_provider):
    suffix = CDN_CNAME_SUFFIXES.get(cdn_provider)
    if not suffix or not prefix:
        return None
    return f'{prefix}.{suffix}'


def _find_root_for_domain(full_domain):
    full_domain = full_domain.lower().strip()
    matches = []
    for root in load_root_domains():
        root_name = (root.get('domain') or '').lower()
        if not root_name:
            continue
        if full_domain == root_name:
            matches.append((root_name, '@', root))
        elif full_domain.endswith('.' + root_name):
            rr = full_domain[:-(len(root_name) + 1)]
            if rr:
                matches.append((root_name, rr, root))
    if not matches:
        return None, None, None
    root_name, rr, root = max(matches, key=lambda item: len(item[0]))
    return root_name, rr, root


def _rr_matches(record_rr, target_rr):
    record_rr = (record_rr or '').strip()
    target_rr = (target_rr or '').strip()
    if target_rr == '@':
        return record_rr in ('', '@')
    return record_rr == target_rr


def _pick_cname_record(records, rr):
    cname_records = [item for item in records if (item.get('record_type') or '').upper() == 'CNAME']
    if not cname_records:
        return None

    matched = [item for item in cname_records if _rr_matches(item.get('sub_domain'), rr)]
    candidates = matched or cname_records

    for item in candidates:
        if _extract_cname_prefix(item.get('value')):
            return item
    return candidates[0]


def sync_cdn_cname(full_domain, cdn_provider):
    suffix = CDN_CNAME_SUFFIXES.get(cdn_provider)
    if not suffix:
        return {
            'success': True,
            'skipped': True,
            'message': f'CDN 提供商 {cdn_provider} 未配置 CNAME 后缀，跳过 DNS 同步',
        }

    root_domain, rr, root = _find_root_for_domain(full_domain)
    if not root_domain:
        return {
            'success': False,
            'message': f'未找到 {full_domain} 对应的主域名配置，请先在「主域名」中添加',
        }

    credential = get_dns_credential(root['dns_provider'], root['dns_credential_id'])
    if not credential:
        return {'success': False, 'message': '主域名绑定的 DNS 凭据不存在或已删除'}

    list_result = list_dns_records(
        root_domain,
        root['dns_provider'],
        credential,
        sub_domain=rr,
        record_type='CNAME',
    )
    if not list_result.get('success'):
        return {'success': False, 'message': list_result.get('message') or '查询 DNS CNAME 记录失败'}

    record = _pick_cname_record(list_result.get('records') or [], rr)
    if not record:
        return {
            'success': False,
            'message': f'未找到 {full_domain} 的 CNAME 解析记录，请先在 DNS 中添加',
        }

    prefix = _extract_cname_prefix(record.get('value'))
    if not prefix:
        return {
            'success': False,
            'message': (
                f'现有 CNAME 值 {record.get("value")} 不符合已知后缀 '
                f'({", ".join(KNOWN_CDN_CNAME_SUFFIXES)})，无法自动切换'
            ),
        }

    new_value = _build_cname_value(prefix, cdn_provider)
    if _normalize_host(record.get('value')) == _normalize_host(new_value):
        return {
            'success': True,
            'skipped': True,
            'message': 'DNS CNAME 已是目标后缀，无需修改',
            'old_value': record.get('value'),
            'new_value': new_value,
        }

    update_result = update_dns_record(
        root_domain,
        root['dns_provider'],
        credential,
        record['record_id'],
        rr,
        'CNAME',
        new_value,
        ttl=record.get('ttl'),
        line=record.get('line'),
    )
    if not update_result.get('success'):
        return {
            'success': False,
            'message': update_result.get('message') or '更新 DNS CNAME 记录失败',
        }

    result = {
        'success': True,
        'message': 'DNS CNAME 已同步',
        'root_domain': root_domain,
        'rr': rr,
        'old_value': record.get('value'),
        'new_value': new_value,
        'record_id': record.get('record_id'),
    }
    log({
        'action': 'cdn_dns_cname_sync',
        'domain': full_domain,
        'cdn_provider': cdn_provider,
        'result': result,
    })
    return result
