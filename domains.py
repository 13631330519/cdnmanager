import copy
import threading
import time
from datetime import datetime
from flask import Blueprint, jsonify, request, session
from common import VALID_PROVIDERS, REFRESH_STATUS_NONE, REFRESH_STATUS_REFRESHING, REFRESH_STATUS_COMPLETE, REFRESH_STATUS_FAILED, CDN_CNAME_SUFFIXES, log
from credentials import get_credential
from models import (
    load_domains,
    load_users,
    get_domain,
    upsert_domain,
    update_domain_fields,
    acquire_domain_refresh,
    delete_domain_record,
    get_url_by_id,
    update_url_by_id,
    load_refreshing_domains,
    load_refreshing_urls,
    try_acquire_polling_lease,
)
from providers.akamai import refresh_akamai, check_akamai_refresh
from providers.alicdn import refresh_alicdn, check_alicdn_task
from providers.tencent import refresh_tencentcdn, check_tencent_task
from providers.lingzhi import check_lingzhi_task, refresh_lingzhi
from providers.cdn_dns_sync import sync_cdn_cname

domain_bp = Blueprint('domain_bp', __name__)

def user_can_access_domain(username, domain):
    allowed_users = domain.get('allowed_users')
    if allowed_users is None:
        return True
    if isinstance(allowed_users, list) and ('*' in allowed_users or username in allowed_users):
        return True
    if domain.get('added_by') == username:
        return True
    return False


def get_visible_domains(username, role):
    if role == 'admin':
        return load_domains()
    return [d for d in load_domains() if user_can_access_domain(username, d)]


def parse_allowed_users(raw_value):
    if not raw_value:
        return ['*']
    allowed_users = [u.strip() for u in raw_value.split(',') if u.strip()]
    return ['*'] if not allowed_users else sorted(set(allowed_users))


def record_refresh_submission(domain_name, result):
    refresh_status = result.get('refresh_status')
    if result.get('success') and not result.get('task_id'):
        refresh_status = REFRESH_STATUS_COMPLETE

    updates = {
        'task_id': result.get('task_id'),
        'refresh_task_status': result.get('refresh_task_status'),
        'refresh_task_detail': result.get('refresh_task_detail'),
        'refresh_status': refresh_status if refresh_status is not None else (REFRESH_STATUS_REFRESHING if result.get('success') else REFRESH_STATUS_FAILED),
        'last_refreshed_at': datetime.now().isoformat()
    }
    return update_domain_fields(domain_name, updates)


def map_task_status(status):
    if not status:
        return REFRESH_STATUS_REFRESHING
    status = status.lower()
    if status in ['complete', 'success', 'finished', 'done', 'complete']:
        return REFRESH_STATUS_COMPLETE
    if status in ['failed', 'fail', 'error','timeout','canceled']:
        return REFRESH_STATUS_FAILED
    return REFRESH_STATUS_REFRESHING

def refresh_pending_url_tasks(urls):
    updated = False
    for url in urls:
        if url.get('refresh_status') != REFRESH_STATUS_REFRESHING:
            continue
        task_id = url.get('task_id')
        if not task_id:
            continue

        provider = url.get('provider')
        credential_id = url.get('credential_id')
        credentials = get_credential(provider, credential_id)
        if not credentials:
            url['refresh_status'] = REFRESH_STATUS_FAILED
            url['refresh_task_status'] = None
            url['refresh_task_detail'] = {"error": "绑定凭据不存在"}
            updated = True
            continue

        if provider == 'alicdn':
            task_info = check_alicdn_task(task_id, credentials)
        elif provider == 'tencent':
            task_info = check_tencent_task(task_id, credentials)
        elif provider == 'lingzhi':
            task_info = check_lingzhi_task(url.get('url'), credentials)
        elif provider == 'akamai':
            task_info = check_akamai_refresh(url.get('refresh_task_detail'))
        else:
            continue

        if task_info.get('success'):
            task_status = task_info.get('task_status')
            url['refresh_status'] = map_task_status(task_status)
            url['refresh_task_detail'] = task_info.get('status_detail')
            if url['refresh_status'] == REFRESH_STATUS_COMPLETE:
                url['completed_at'] = datetime.now().isoformat()
            updated = True
        else:
            url['refresh_status'] = REFRESH_STATUS_FAILED
            url['refresh_task_detail'] = {"error": task_info.get('message')}
            updated = True
    return updated,urls

def refresh_pending_tasks(domains):
    updated = False
    for domain_record in domains:
        if domain_record.get('refresh_status') != REFRESH_STATUS_REFRESHING:
            continue
        task_id = domain_record.get('task_id')
        if not task_id:
            continue

        provider = domain_record.get('provider')
        credential_id = domain_record.get('credential_id')
        credentials = get_credential(provider, credential_id)
        if not credentials:
            domain_record['refresh_status'] = REFRESH_STATUS_FAILED
            domain_record['refresh_task_status'] = None
            domain_record['refresh_task_detail'] = {"error": "绑定凭据不存在"}
            updated = True
            continue

        if provider == 'alicdn':
            task_info = check_alicdn_task(task_id, credentials)
        elif provider == 'tencent':
            task_info = check_tencent_task(task_id, credentials)
        elif provider == 'lingzhi':
            task_info = check_lingzhi_task(f"https://{domain_record['domain']}/", credentials)
        elif provider == 'akamai':
            task_info = check_akamai_refresh(domain_record.get('refresh_task_detail'))
        else:
            continue

        if task_info.get('success'):
            task_status = task_info.get('task_status')
            domain_record['refresh_status'] = map_task_status(task_status)
            domain_record['refresh_task_status'] = task_status
            domain_record['refresh_task_detail'] = task_info.get('status_detail')
            if domain_record['refresh_status'] == REFRESH_STATUS_COMPLETE:
                domain_record['last_refreshed_at'] = datetime.now().isoformat()
            updated = True
        else:
            domain_record['refresh_status'] = REFRESH_STATUS_FAILED
            domain_record['refresh_task_detail'] = {"error": task_info.get('message')}
            updated = True
    return updated, domains


DOMAIN_POLL_FIELDS = ('refresh_status', 'refresh_task_status', 'refresh_task_detail', 'last_refreshed_at')
URL_POLL_FIELDS = ('refresh_status', 'refresh_task_detail', 'completed_at')


def poll_domain_tasks_once():
    snapshot = copy.deepcopy(load_refreshing_domains())
    if not snapshot:
        return
    updated, polled = refresh_pending_tasks(snapshot)
    if not updated:
        return

    for polled_record in polled:
        domain_name = polled_record.get('domain')
        if not domain_name:
            continue
        current = get_domain(domain_name)
        if not current or current.get('refresh_status') != REFRESH_STATUS_REFRESHING:
            continue
        if current.get('task_id') != polled_record.get('task_id'):
            continue
        updates = {field: polled_record.get(field) for field in DOMAIN_POLL_FIELDS if polled_record.get(field) is not None}
        if updates:
            update_domain_fields(domain_name, updates)


def poll_url_tasks_once():
    snapshot = copy.deepcopy(load_refreshing_urls())
    if not snapshot:
        return
    updated, polled = refresh_pending_url_tasks(snapshot)
    if not updated:
        return

    for polled_record in polled:
        url_id = polled_record.get('id')
        if not url_id:
            continue
        current = get_url_by_id(url_id)
        if not current or current.get('refresh_status') != REFRESH_STATUS_REFRESHING:
            continue
        if current.get('task_id') != polled_record.get('task_id'):
            continue
        updates = {field: polled_record.get(field) for field in URL_POLL_FIELDS if polled_record.get(field) is not None}
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


def find_bound_domain(host):
    host = host.lower().strip()
    domains = load_domains()
    candidates = [d for d in domains if d.get('domain') and (host == d['domain'].lower() or host.endswith('.' + d['domain'].lower()))]
    if not candidates:
        return None
    return max(candidates, key=lambda d: len(d['domain']))


@domain_bp.route('/add_domain', methods=['POST'])
def add_domain():
    if 'username' not in session:
        return jsonify({"error": "未登录"}), 401
    user = next((u for u in load_users() if u['username'] == session['username']), None)
    if user['role'] != 'admin':
        return jsonify({"error": "无权限添加域名"}), 403
    domain = request.form.get('domain', '').strip()
    domain_name = request.form.get('domain_name', '').strip()
    provider = request.form.get('provider')
    credential_id = request.form.get('credential_id')
    allowed_users = parse_allowed_users(request.form.get('allowed_users', '').strip())
    cpcode = request.form.get('cpcode', '').strip() or None
    if not domain or not domain_name or not provider or not credential_id:
        return jsonify({"error": "域名、域名名称、提供商和凭据ID必填"}), 400
    if provider == 'akamai' and not cpcode:
        return jsonify({"error": "Akamai 域名必须填写 CP Code"}), 400
    if provider not in VALID_PROVIDERS:
        return jsonify({"error": "不支持的CDN提供商"}), 400
    credential = get_credential(provider, credential_id)
    if not credential:
        return jsonify({"error": "请选择有效的凭据"}), 400

    # use atomic upsert
    existing = get_domain(domain)
    if existing:
        return jsonify({"error": "域名已存在"}), 400
    upsert_domain({
        "domain": domain,
        "domain_name": domain_name,
        "provider": provider,
        "credential_id": credential_id,
        "cpcode": cpcode,
        "allowed_users": allowed_users,
        "added_by": user['username'],
        "added_at": datetime.now().isoformat(),
        "refresh_status": REFRESH_STATUS_NONE,
        "last_refreshed_at": None,
        "task_id": None,
        "refresh_task_status": None,
        "refresh_task_detail": None
    })
    return jsonify({"success": True, "message": "域名添加成功"})


@domain_bp.route('/edit_domain', methods=['POST'])
def edit_domain():
    if 'username' not in session:
        return jsonify({"error": "未登录"}), 401
    user = next((u for u in load_users() if u['username'] == session['username']), None)
    if user['role'] != 'admin':
        return jsonify({"error": "无权限修改域名"}), 403
    domain = request.form.get('domain')
    domain_name = request.form.get('domain_name', '').strip()
    provider = request.form.get('provider')
    credential_id = request.form.get('credential_id')
    allowed_users = parse_allowed_users(request.form.get('allowed_users', '').strip())
    cpcode = request.form.get('cpcode', '').strip() or None
    if not domain or not domain_name or not provider or not credential_id:
        return jsonify({"error": "域名、域名名称、提供商和凭据ID必填"}), 400
    if provider == 'akamai' and not cpcode:
        return jsonify({"error": "Akamai 域名必须填写 CP Code"}), 400
    if provider not in VALID_PROVIDERS:
        return jsonify({"error": "不支持的CDN提供商"}), 400
    credential = get_credential(provider, credential_id)
    if not credential:
        return jsonify({"error": "请选择有效的凭据"}), 400

    existing = get_domain(domain)
    if not existing:
        return jsonify({"error": "域名不存在"}), 404
    provider_changed = existing.get('provider') != provider
    upsert_domain({
        'domain': domain,
        'domain_name': domain_name,
        'provider': provider,
        'credential_id': credential_id,
        'cpcode': cpcode if provider == 'akamai' else None,
        'allowed_users': allowed_users,
        'added_by': existing.get('added_by'),
        'added_at': existing.get('added_at'),
        'task_id': None,
        'refresh_task_status': None,
        'refresh_task_detail': None,
        'refresh_status': REFRESH_STATUS_NONE,
        'last_refreshed_at': None
    })

    response = {"success": True, "message": "域名已更新"}
    if provider_changed and provider in CDN_CNAME_SUFFIXES:
        dns_result = sync_cdn_cname(domain, provider)
        response['dns_sync'] = dns_result
        if dns_result.get('success') and not dns_result.get('skipped'):
            response['message'] = f"域名已更新，DNS CNAME 已同步为 {dns_result.get('new_value')}"
        elif dns_result.get('success') and dns_result.get('skipped'):
            response['message'] = f"域名已更新（{dns_result.get('message')}）"
        else:
            response['message'] = f"域名已更新，但 DNS CNAME 同步失败：{dns_result.get('message')}"

    return jsonify(response)


@domain_bp.route('/refresh_domain', methods=['POST'])
def refresh_domain():
    if 'username' not in session:
        return jsonify({"error": "未登录"}), 401
    domain = request.form.get('domain')
    if not domain:
        return jsonify({"error": "域名不能为空"}), 400
    domains = load_domains()
    target = next((d for d in domains if d['domain'] == domain), None)
    if not target:
        return jsonify({"error": "域名不存在"}), 404
    user = next((u for u in load_users() if u['username'] == session['username']), None)
    if not user:
        return jsonify({"error": "未登录"}), 401
    if user.get('role') != 'admin' and not user_can_access_domain(user['username'], target):
        return jsonify({"error": "无权限刷新该域名"}), 403
    provider = target.get('provider')
    if provider not in VALID_PROVIDERS:
        return jsonify({"error": "不支持的CDN提供商"}), 400
    credential_id = target.get('credential_id')
    if not credential_id:
        return jsonify({"error": "域名未绑定凭据，请先绑定 provider_credentials 中的凭据"}), 400
    credential = get_credential(provider, credential_id)
    if not credential:
        return jsonify({"error": "绑定的凭据不存在或已被删除"}), 400

    # acquire refresh flag atomically
    if not acquire_domain_refresh(domain):
        if not get_domain(domain):
            return jsonify({"error": "域名不存在"}), 404
        return jsonify({"error": "该域名正在刷新中，请稍后"}), 400

    try:
        if provider == "alicdn":
            result = refresh_alicdn(domain, credential)
        elif provider == "tencent":
            result = refresh_tencentcdn(domain, credential)
        elif provider == "lingzhi":
            result = refresh_lingzhi(domain, credential)
        elif provider == "akamai":
            result = refresh_akamai(domain, credential, cpcode=target.get('cpcode'))
        else:
            return jsonify({"error": "不支持的提供商"}), 400
    except Exception as exc:
        update_domain_fields(domain, {
            'refresh_status': REFRESH_STATUS_FAILED,
            'refresh_task_detail': {"error": str(exc)}
        })
        return jsonify({"error": f"刷新请求异常: {exc}"}), 500

    record_refresh_submission(domain, result)

    log_entry = {
        "user":user['username'],
        "domain": domain,
        "provider": provider,
        "refreshed_by": session['username'],
        "refreshed_at": datetime.now().isoformat(),
        "status": "success" if result.get('success') else "failed",
        "result": result
    }
    log(log_entry)
    return jsonify(result)


@domain_bp.route('/delete_domain', methods=['POST'])
def delete_domain():
    if 'username' not in session:
        return jsonify({"error": "未登录"}), 401
    user = next((u for u in load_users() if u['username'] == session['username']), None)
    if user['role'] != 'admin':
        return jsonify({"error": "无权限删除域名"}), 403
    domain = request.form.get('domain')
    
    # delete atomically
    delete_domain_record(domain)

    return jsonify({"success": True, "message": "域名已删除"})
