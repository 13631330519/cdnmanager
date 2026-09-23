import copy
import threading
import time
from datetime import datetime
from flask import Blueprint, jsonify, request, session
from cdnmanager.common import VALID_PROVIDERS, REFRESH_STATUS_NONE, REFRESH_STATUS_REFRESHING, REFRESH_STATUS_FAILED, CDN_CNAME_SUFFIXES, can_edit_domain_provider, can_manage_all_domains, log
from cdnmanager.db import (
    find_bound_domain,
    get_credential,
    get_domain,
    get_visible_domains,
    load_domains,
    upsert_domain,
    update_domain_fields,
    acquire_domain_refresh,
    delete_domain_record,
    get_url_by_id,
    update_url_by_id,
    load_refreshing_domains,
    load_refreshing_urls,
    try_acquire_polling_lease,
    get_environment,
    get_project,
    sync_domain_tags_from_ids,
)
from cdnmanager.providers.cdn import sync_cdn_cname
from cdnmanager.routes.common import get_session_user, require_login
from cdnmanager.services.refresh_service import (
    poll_domain_record,
    poll_url_record,
    record_domain_refresh,
    refresh_and_record,
)

domain_bp = Blueprint('domain_bp', __name__)


def parse_allowed_users(raw_value):
    if not raw_value:
        return ['*']
    allowed_users = [u.strip() for u in raw_value.split(',') if u.strip()]
    return ['*'] if not allowed_users else sorted(set(allowed_users))


def parse_group_tags(raw_value):
    if not raw_value:
        return []
    tags = [tag.strip() for tag in raw_value.split(',') if tag.strip()]
    return sorted(set(tags))


def _get_session_user_or_error():
    login_error = require_login()
    if login_error is not None:
        return None, login_error
    user = get_session_user()
    if not user:
        return None, (jsonify({"error": "未登录"}), 401)
    return user, None


def parse_project_binding(form):
    project_id = (form.get('project_id') or '').strip() or None
    environment_id = (form.get('environment_id') or '').strip() or None
    if environment_id and not project_id:
        environment = get_environment(environment_id)
        if environment:
            project_id = environment['project_id']
    if project_id and not get_project(project_id):
        project_id = None
        environment_id = None
    if environment_id and not get_environment(environment_id):
        environment_id = None
    if environment_id:
        environment = get_environment(environment_id)
        if not environment or environment['project_id'] != project_id:
            environment_id = None
    projects, environments = sync_domain_tags_from_ids(project_id, environment_id)
    return project_id, environment_id, projects, environments


record_refresh_submission = record_domain_refresh

DOMAIN_POLL_FIELDS = ('refresh_status', 'refresh_task_status', 'refresh_task_detail', 'last_refreshed_at')
URL_POLL_FIELDS = ('refresh_status', 'refresh_task_detail', 'completed_at')


def poll_domain_tasks_once():
    snapshot = copy.deepcopy(load_refreshing_domains())
    if not snapshot:
        return
    updated = False
    for polled_record in snapshot:
        if not poll_domain_record(polled_record):
            continue
        updated = True
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
    updated = False
    for polled_record in snapshot:
        if not poll_url_record(polled_record):
            continue
        updated = True
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


@domain_bp.route('/add_domain', methods=['POST'])
def add_domain():
    user, auth_error = _get_session_user_or_error()
    if auth_error:
        return auth_error
    if user['role'] != 'admin':
        return jsonify({"error": "无权限添加域名"}), 403
    domain = request.form.get('domain', '').strip()
    domain_name = request.form.get('domain_name', '').strip()
    provider = request.form.get('provider')
    credential_id = request.form.get('credential_id')
    project_id, environment_id, projects, environments = parse_project_binding(request.form)
    cpcode = request.form.get('cpcode', '').strip() or None
    if not domain or not domain_name or not provider or not credential_id:
        return jsonify({"error": "域名、域名名称、提供商和凭据ID必填"}), 400
    if not project_id or not environment_id:
        return jsonify({"error": "新加域名必须绑定项目和环境"}), 400
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
        "project_id": project_id,
        "environment_id": environment_id,
        "projects": projects,
        "environments": environments,
        "allowed_users": ['*'],
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
    user, auth_error = _get_session_user_or_error()
    if auth_error:
        return auth_error
    if not can_edit_domain_provider(user.get('role')):
        return jsonify({"error": "无权限修改域名"}), 403
    domain = request.form.get('domain')
    existing = get_domain(domain)
    if not existing:
        return jsonify({"error": "域名不存在"}), 404

    if user.get('role') == 'domain_admin':
        domain_name = existing.get('domain_name', '').strip()
    else:
        domain_name = request.form.get('domain_name', '').strip()

    project_id, environment_id, projects, environments = parse_project_binding(request.form)
    provider = request.form.get('provider')
    credential_id = request.form.get('credential_id')
    cpcode = request.form.get('cpcode', '').strip() or None
    if not domain or not domain_name or not provider or not credential_id:
        return jsonify({"error": "域名、域名名称、提供商和凭据ID必填"}), 400
    if not project_id or not environment_id:
        return jsonify({"error": "域名必须绑定项目和环境"}), 400
    if provider == 'akamai' and not cpcode:
        return jsonify({"error": "Akamai 域名必须填写 CP Code"}), 400
    if provider not in VALID_PROVIDERS:
        return jsonify({"error": "不支持的CDN提供商"}), 400
    credential = get_credential(provider, credential_id)
    if not credential:
        return jsonify({"error": "请选择有效的凭据"}), 400

    provider_changed = existing.get('provider') != provider
    upsert_domain({
        'domain': domain,
        'domain_name': domain_name,
        'provider': provider,
        'credential_id': credential_id,
        'cpcode': cpcode if provider == 'akamai' else None,
        'project_id': project_id,
        'environment_id': environment_id,
        'projects': projects,
        'environments': environments,
        'allowed_users': ['*'],
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
    user, auth_error = _get_session_user_or_error()
    if auth_error:
        return auth_error
    domain = request.form.get('domain')
    if not domain:
        return jsonify({"error": "域名不能为空"}), 400
    domains = load_domains()
    target = next((d for d in domains if d['domain'] == domain), None)
    if not target:
        return jsonify({"error": "域名不存在"}), 404
    if not can_manage_all_domains(user.get('role')) and not user_can_access_domain(user['username'], user.get('role'), target):
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
        result = refresh_and_record(target, credential, record_url=True)
        if result.get('error') and not result.get('success'):
            return jsonify({"error": result.get('error', '刷新失败')}), 400
    except Exception as exc:
        update_domain_fields(domain, {
            'refresh_status': REFRESH_STATUS_FAILED,
            'refresh_task_detail': {"error": str(exc)}
        })
        return jsonify({"error": f"刷新请求异常: {exc}"}), 500

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
    user, auth_error = _get_session_user_or_error()
    if auth_error:
        return auth_error
    if user['role'] != 'admin':
        return jsonify({"error": "无权限删除域名"}), 403
    domain = request.form.get('domain')
    
    # delete atomically
    delete_domain_record(domain)

    return jsonify({"success": True, "message": "域名已删除"})
