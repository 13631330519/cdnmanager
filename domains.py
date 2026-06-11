import json
import os
import threading
import time
from datetime import datetime
from flask import Blueprint, jsonify, request, session
from common import DOMAIN_FILE, DATA_DIR, VALID_PROVIDERS, REFRESH_STATUS_NONE, REFRESH_STATUS_REFRESHING, REFRESH_STATUS_COMPLETE, REFRESH_STATUS_FAILED, DOMAINS_LOCK,log
from credentials import get_credential
from providers.akamai import refresh_akamai
from providers.alicdn import refresh_alicdn, check_alicdn_task
from providers.tencent import refresh_tencentcdn, check_tencent_task
from providers.lingzhi import refresh_lingzhi
from users import load_users

domain_bp = Blueprint('domain_bp', __name__)


def load_domains():
    with DOMAINS_LOCK:
        with open(DOMAIN_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)


def save_domains(domains):
    with DOMAINS_LOCK:
        with open(DOMAIN_FILE, 'w', encoding='utf-8') as f:
            json.dump(domains, f, indent=2, ensure_ascii=False)


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


def update_domain_record(domain_name, updates):
    domains = load_domains()
    target = next((d for d in domains if d['domain'] == domain_name), None)
    if not target:
        return False
    target.update(updates)
    save_domains(domains)
    return True


def record_refresh_submission(domain_name, result):
    refresh_status = result.get('refresh_status')
    if result.get('success') and not result.get('task_id'):
        refresh_status = REFRESH_STATUS_COMPLETE

    updates = {
        'task_id': result.get('task_id'),
        'refresh_task_action': result.get('refresh_task_action'),
        'refresh_task_status': None,
        'refresh_task_detail': None,
        'refresh_status': refresh_status if refresh_status is not None else (REFRESH_STATUS_REFRESHING if result.get('success') else REFRESH_STATUS_FAILED),
        'last_refreshed_at': datetime.now().isoformat()
    }
    return update_domain_record(domain_name, updates)


def map_task_status(status):
    if not status:
        return REFRESH_STATUS_REFRESHING
    status = status.lower()
    if status in ['complete', 'success', 'finished', 'done', 'complete']:
        return REFRESH_STATUS_COMPLETE
    if status in ['failed', 'fail', 'error','timeout','canceled']:
        return REFRESH_STATUS_FAILED
    return REFRESH_STATUS_REFRESHING


def refresh_pending_tasks():
    domains = load_domains()
    updated = False
    for domain_record in domains:
        if domain_record.get('refresh_status') != REFRESH_STATUS_REFRESHING:
            continue
        task_id = domain_record.get('task_id')
        task_action = domain_record.get('refresh_task_action')
        if not task_id or not task_action:
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

    if updated:
        save_domains(domains)


def start_task_polling_thread():
    def worker():
        while True:
            try:
                refresh_pending_tasks()
            except Exception:
                pass
            time.sleep(10)

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
    if not domain or not domain_name or not provider or not credential_id:
        return jsonify({"error": "域名、域名名称、提供商和凭据ID必填"}), 400
    if provider not in VALID_PROVIDERS:
        return jsonify({"error": "不支持的CDN提供商"}), 400
    credential = get_credential(provider, credential_id)
    if not credential:
        return jsonify({"error": "请选择有效的凭据"}), 400
    domains = load_domains()
    if any(d['domain'] == domain for d in domains):
        return jsonify({"error": "域名已存在"}), 400
    domains.append({
        "domain": domain,
        "domain_name": domain_name,
        "provider": provider,
        "credential_id": credential_id,
        "allowed_users": allowed_users,
        "added_by": user['username'],
        "added_at": datetime.now().isoformat(),
        "refresh_status": REFRESH_STATUS_NONE,
        "last_refreshed_at": None,
        "task_id": None,
        "refresh_task_action": None,
        "refresh_task_status": None,
        "refresh_task_detail": None
    })
    save_domains(domains)
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
    if not domain or not domain_name or not provider or not credential_id:
        return jsonify({"error": "域名、域名名称、提供商和凭据ID必填"}), 400
    if provider not in VALID_PROVIDERS:
        return jsonify({"error": "不支持的CDN提供商"}), 400
    credential = get_credential(provider, credential_id)
    if not credential:
        return jsonify({"error": "请选择有效的凭据"}), 400
    domains = load_domains()
    target = next((d for d in domains if d['domain'] == domain), None)
    if not target:
        return jsonify({"error": "域名不存在"}), 404
    target['domain_name'] = domain_name
    target['provider'] = provider
    target['credential_id'] = credential_id
    target['allowed_users'] = allowed_users
    target['task_id'] = None
    target['refresh_task_action'] = None
    target['refresh_task_status'] = None
    target['refresh_task_detail'] = None
    target['refresh_status'] = REFRESH_STATUS_NONE
    target['last_refreshed_at'] = None
    save_domains(domains)
    return jsonify({"success": True, "message": "域名已更新"})


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
    if target.get('refresh_status') == REFRESH_STATUS_REFRESHING:
        return jsonify({"error": "该域名正在刷新中，请稍后"}), 400
    provider = target.get('provider')
    if provider not in VALID_PROVIDERS:
        return jsonify({"error": "不支持的CDN提供商"}), 400
    credential_id = target.get('credential_id')
    if not credential_id:
        return jsonify({"error": "域名未绑定凭据，请先绑定 provider_credentials 中的凭据"}), 400
    credential = get_credential(provider, credential_id)
    if not credential:
        return jsonify({"error": "绑定的凭据不存在或已被删除"}), 400
    if provider == "alicdn":
        result = refresh_alicdn(domain, credential)
    elif provider == "tencent":
        result = refresh_tencentcdn(domain, credential)
    elif provider == "lingzhi":
        result = refresh_lingzhi(domain, credential)
    elif provider == "akamai":
        result = refresh_akamai(domain, credential)
    else:
        return jsonify({"error": "不支持的提供商"}), 400

    if result.get('success'):
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
    domains = load_domains()
    domains = [d for d in domains if d['domain'] != domain]
    save_domains(domains)
    return jsonify({"success": True, "message": "域名已删除"})
