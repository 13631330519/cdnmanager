"""CDN refresh orchestration — single entry for submit, poll, and record."""

import copy
import threading
import time
from datetime import datetime

from cdnmanager.common import (
    REFRESH_STATUS_COMPLETE,
    REFRESH_STATUS_FAILED,
    REFRESH_STATUS_REFRESHING,
)
from cdnmanager.db import (
    get_credential,
    insert_url_record,
    update_domain_fields,
    load_refreshing_domains,
    load_refreshing_urls,
    get_domain,
    get_url_by_id,
    update_url_by_id,
    try_acquire_polling_lease,
)
from cdnmanager.providers.cdn import(
    check_akamai_refresh, refresh_akamai,
    check_alicdn_task, refresh_alicdn,
    check_ctyun_task, refresh_ctyun,
    check_lingzhi_task, refresh_lingzhi,
    check_tencent_task, refresh_tencentcdn,
    check_volcengine_task, refresh_volcengine,
    refresh_x7host
)
DOMAIN_POLL_FIELDS = ('refresh_status', 'refresh_task_status', 'refresh_task_detail', 'last_refreshed_at')
URL_POLL_FIELDS = ('refresh_status', 'refresh_task_detail', 'completed_at')


def map_task_status(status):
    if not status:
        return REFRESH_STATUS_REFRESHING
    status = status.lower()
    if status in ('complete', 'completed', 'success', 'finished', 'done'):
        return REFRESH_STATUS_COMPLETE
    if status in ('failed', 'fail', 'error', 'timeout', 'canceled'):
        return REFRESH_STATUS_FAILED
    if status in ('running', 'processing', 'process'):
        return REFRESH_STATUS_REFRESHING
    return REFRESH_STATUS_REFRESHING


def normalize_refresh_status(result):
    refresh_status = result.get('refresh_status')
    if result.get('success') and not result.get('task_id'):
        return REFRESH_STATUS_COMPLETE
    if refresh_status is not None:
        return refresh_status
    return REFRESH_STATUS_REFRESHING if result.get('success') else REFRESH_STATUS_FAILED


def submit_refresh(provider, domain, credential, url=None, cpcode=None):
    if provider == 'alicdn':
        return refresh_alicdn(domain, credential, url=url)
    if provider == 'tencent':
        return refresh_tencentcdn(domain, credential, url=url)
    if provider == 'lingzhi':
        return refresh_lingzhi(domain, credential, url=url)
    if provider == 'akamai':
        return refresh_akamai(domain, credential, url=url, cpcode=cpcode)
    if provider == 'ctyun':
        return refresh_ctyun(domain, credential, url=url)
    if provider == 'volcengine':
        return refresh_volcengine(domain, credential, url=url)
    if provider == 'x7host':
        return refresh_x7host(domain, credential, url=url)
    return {'success': False, 'error': f'不支持的提供商: {provider}'}


def check_refresh_task(provider, task_id, credential, url=None, task_detail=None):
    if provider == 'alicdn':
        return check_alicdn_task(task_id, credential)
    if provider == 'tencent':
        return check_tencent_task(task_id, credential)
    if provider == 'lingzhi':
        return check_lingzhi_task(url or '', credential)
    if provider == 'akamai':
        return check_akamai_refresh(task_detail)
    if provider == 'ctyun':
        return check_ctyun_task(task_id, credential)
    if provider == 'volcengine':
        return check_volcengine_task(task_id, credential, task_detail)
    return None


def record_domain_refresh(domain_name, result):
    refresh_status = normalize_refresh_status(result)
    updates = {
        'task_id': result.get('task_id'),
        'refresh_task_status': result.get('refresh_task_status'),
        'refresh_task_detail': result.get('refresh_task_detail'),
        'refresh_status': refresh_status,
        'last_refreshed_at': datetime.now().isoformat(),
    }
    update_domain_fields(domain_name, updates)
    return updates


def record_url_refresh(domain, provider, credential_id, result, url):
    refresh_status = normalize_refresh_status(result)
    insert_url_record({
        'domain': domain,
        'url': url,
        'provider': provider,
        'credential_id': credential_id,
        'submitted_at': datetime.now().isoformat(),
        'completed_at': datetime.now().isoformat() if refresh_status == REFRESH_STATUS_COMPLETE else None,
        'task_id': result.get('task_id'),
        'refresh_status': refresh_status,
        'refresh_task_detail': result.get('refresh_task_detail'),
    })


def refresh_and_record(domain_record, credential, url=None, record_url=True):
    """Submit refresh, update domain state, optionally append URL refresh log."""
    provider = domain_record.get('provider')
    domain = domain_record['domain']
    result = submit_refresh(
        provider,
        domain,
        credential,
        url=url,
        cpcode=domain_record.get('cpcode'),
    )
    record_domain_refresh(domain, result)
    if record_url:
        display_url = url or f'https://{domain}/'
        record_url_refresh(domain, provider, domain_record.get('credential_id'), result, display_url)
    return result


def poll_domain_record(domain_record):
    if domain_record.get('refresh_status') != REFRESH_STATUS_REFRESHING:
        return False
    task_id = domain_record.get('task_id')
    if not task_id:
        return False

    provider = domain_record.get('provider')
    credential_id = domain_record.get('credential_id')
    credential = get_credential(provider, credential_id)
    if not credential:
        domain_record['refresh_status'] = REFRESH_STATUS_FAILED
        domain_record['refresh_task_status'] = None
        domain_record['refresh_task_detail'] = {'error': '绑定凭据不存在'}
        return True

    poll_url = f"https://{domain_record['domain']}/"
    task_info = check_refresh_task(
        provider,
        task_id,
        credential,
        url=poll_url,
        task_detail=domain_record.get('refresh_task_detail'),
    )
    if not task_info:
        return False

    if task_info.get('success'):
        task_status = task_info.get('task_status')
        domain_record['refresh_status'] = map_task_status(task_status)
        domain_record['refresh_task_status'] = task_status
        domain_record['refresh_task_detail'] = task_info.get('status_detail')
        if domain_record['refresh_status'] == REFRESH_STATUS_COMPLETE:
            domain_record['last_refreshed_at'] = datetime.now().isoformat()
    else:
        domain_record['refresh_status'] = REFRESH_STATUS_FAILED
        domain_record['refresh_task_detail'] = {'error': task_info.get('message')}
    return True


def poll_url_record(url_record):
    if url_record.get('refresh_status') != REFRESH_STATUS_REFRESHING:
        return False
    task_id = url_record.get('task_id')
    if not task_id:
        return False

    provider = url_record.get('provider')
    credential_id = url_record.get('credential_id')
    credential = get_credential(provider, credential_id)
    if not credential:
        url_record['refresh_status'] = REFRESH_STATUS_FAILED
        url_record['refresh_task_detail'] = {'error': '绑定凭据不存在'}
        return True

    task_info = check_refresh_task(
        provider,
        task_id,
        credential,
        url=url_record.get('url'),
        task_detail=url_record.get('refresh_task_detail'),
    )
    if not task_info:
        return False

    if task_info.get('success'):
        task_status = task_info.get('task_status')
        url_record['refresh_status'] = map_task_status(task_status)
        url_record['refresh_task_detail'] = task_info.get('status_detail')
        if url_record['refresh_status'] == REFRESH_STATUS_COMPLETE:
            url_record['completed_at'] = datetime.now().isoformat()
    else:
        url_record['refresh_status'] = REFRESH_STATUS_FAILED
        url_record['refresh_task_detail'] = {'error': task_info.get('message')}
    return True


def poll_domain_tasks_once():
    snapshot = copy.deepcopy(load_refreshing_domains())
    if not snapshot:
        return
    for polled_record in snapshot:
        if not poll_domain_record(polled_record):
            continue
        domain_name = polled_record.get('domain')
        if not domain_name:
            continue
        current = get_domain(domain_name)
        if not current or current.get('refresh_status') != REFRESH_STATUS_REFRESHING:
            continue
        if current.get('task_id') != polled_record.get('task_id'):
            continue
        updates = {
            field: polled_record.get(field)
            for field in DOMAIN_POLL_FIELDS
            if polled_record.get(field) is not None
        }
        if updates:
            update_domain_fields(domain_name, updates)


def poll_url_tasks_once():
    snapshot = copy.deepcopy(load_refreshing_urls())
    if not snapshot:
        return
    for polled_record in snapshot:
        if not poll_url_record(polled_record):
            continue
        url_id = polled_record.get('id')
        if not url_id:
            continue
        current = get_url_by_id(url_id)
        if not current or current.get('refresh_status') != REFRESH_STATUS_REFRESHING:
            continue
        if current.get('task_id') != polled_record.get('task_id'):
            continue
        updates = {
            field: polled_record.get(field)
            for field in URL_POLL_FIELDS
            if polled_record.get(field) is not None
        }
        if updates:
            update_url_by_id(url_id, updates)


def start_task_polling_thread():
    def worker():
        while True:
            try:
                if try_acquire_polling_lease():
                    poll_domain_tasks_once()
                    poll_url_tasks_once()
            except Exception:
                pass
            time.sleep(30)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread

