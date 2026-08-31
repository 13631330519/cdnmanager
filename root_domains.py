from datetime import datetime
from flask import Blueprint, jsonify, request, session

from common import DNS_PROVIDERS, log
from models import (
    load_root_domains,
    get_root_domain,
    upsert_root_domain,
    delete_root_domain,
    get_dns_credential,
    get_user,
)
from providers.dns_service import list_dns_records, update_dns_record, create_dns_record, delete_dns_record

root_domain_bp = Blueprint('root_domain_bp', __name__)


def _require_admin():
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401
    user = get_user(session['username'])
    if not user or user.get('role') != 'admin':
        return jsonify({'error': '无权限'}), 403
    return None


def _get_dns_context(root_domain_name):
    root = get_root_domain(root_domain_name)
    if not root:
        return None, jsonify({'error': '主域名不存在'}), 404
    provider = root.get('dns_provider')
    credential = get_dns_credential(provider, root.get('dns_credential_id'))
    if not credential:
        return None, jsonify({'error': 'DNS 凭据不存在或已删除'}), 400
    return {'root': root, 'credential': credential}, None, None


@root_domain_bp.route('/add_root_domain', methods=['POST'])
def add_root_domain():
    denied = _require_admin()
    if denied:
        return denied

    domain = request.form.get('domain', '').strip().lower()
    domain_name = request.form.get('domain_name', '').strip()
    dns_provider = request.form.get('dns_provider')
    dns_credential_id = request.form.get('dns_credential_id', '').strip()

    if not domain or not domain_name or not dns_provider or not dns_credential_id:
        return jsonify({'error': '主域名、名称、DNS 服务商和凭据必填'}), 400
    if dns_provider not in DNS_PROVIDERS:
        return jsonify({'error': '不支持的 DNS 服务商'}), 400
    if get_root_domain(domain):
        return jsonify({'error': '主域名已存在'}), 400
    if not get_dns_credential(dns_provider, dns_credential_id):
        return jsonify({'error': '请选择有效的 DNS 凭据'}), 400

    now = datetime.now().isoformat()
    upsert_root_domain({
        'domain': domain,
        'domain_name': domain_name,
        'dns_provider': dns_provider,
        'dns_credential_id': dns_credential_id,
        'added_by': session['username'],
        'added_at': now,
        'updated_at': now,
    })
    return jsonify({'success': True, 'message': '主域名已添加'})


@root_domain_bp.route('/edit_root_domain', methods=['POST'])
def edit_root_domain():
    denied = _require_admin()
    if denied:
        return denied

    domain = request.form.get('domain', '').strip().lower()
    domain_name = request.form.get('domain_name', '').strip()
    dns_provider = request.form.get('dns_provider')
    dns_credential_id = request.form.get('dns_credential_id', '').strip()

    if not domain or not domain_name or not dns_provider or not dns_credential_id:
        return jsonify({'error': '主域名、名称、DNS 服务商和凭据必填'}), 400
    if dns_provider not in DNS_PROVIDERS:
        return jsonify({'error': '不支持的 DNS 服务商'}), 400
    if not get_root_domain(domain):
        return jsonify({'error': '主域名不存在'}), 404
    if not get_dns_credential(dns_provider, dns_credential_id):
        return jsonify({'error': '请选择有效的 DNS 凭据'}), 400

    existing = get_root_domain(domain)
    upsert_root_domain({
        'domain': domain,
        'domain_name': domain_name,
        'dns_provider': dns_provider,
        'dns_credential_id': dns_credential_id,
        'added_by': existing.get('added_by'),
        'added_at': existing.get('added_at'),
        'updated_at': datetime.now().isoformat(),
    })
    return jsonify({'success': True, 'message': '主域名已更新'})


@root_domain_bp.route('/delete_root_domain', methods=['POST'])
def delete_root_domain_route():
    denied = _require_admin()
    if denied:
        return denied

    domain = request.form.get('domain', '').strip().lower()
    if not domain:
        return jsonify({'error': '主域名不能为空'}), 400
    delete_root_domain(domain)
    return jsonify({'success': True, 'message': '主域名已删除'})


@root_domain_bp.route('/internal/dns/records', methods=['GET'])
def internal_list_dns_records():
    denied = _require_admin()
    if denied:
        return denied

    root_domain = request.args.get('root_domain', '').strip().lower()
    sub_domain = request.args.get('sub_domain', '').strip() or None
    record_type = request.args.get('record_type', '').strip() or None
    if not root_domain:
        return jsonify({'error': 'root_domain 必填'}), 400

    context, error_response, status = _get_dns_context(root_domain)
    if error_response:
        return error_response, status

    result = list_dns_records(
        root_domain,
        context['root']['dns_provider'],
        context['credential'],
        sub_domain=sub_domain,
        record_type=record_type,
    )
    if not result.get('success'):
        return jsonify(result), 400
    return jsonify(result)


@root_domain_bp.route('/internal/dns/record/update', methods=['POST'])
def internal_update_dns_record():
    denied = _require_admin()
    if denied:
        return denied

    root_domain = request.form.get('root_domain', '').strip().lower()
    record_id = request.form.get('record_id', '').strip()
    sub_domain = request.form.get('sub_domain', '').strip()
    record_type = request.form.get('record_type', '').strip()
    value = request.form.get('value', '').strip()
    ttl = request.form.get('ttl', '').strip() or None
    line = request.form.get('line', '').strip() or None

    if not all([root_domain, record_id, sub_domain, record_type, value]):
        return jsonify({'error': 'root_domain、record_id、sub_domain、record_type、value 必填'}), 400

    context, error_response, status = _get_dns_context(root_domain)
    if error_response:
        return error_response, status

    result = update_dns_record(
        root_domain,
        context['root']['dns_provider'],
        context['credential'],
        record_id,
        sub_domain,
        record_type,
        value,
        ttl=ttl,
        line=line,
    )
    log({
        'action': 'dns_update_record',
        'user': session.get('username'),
        'root_domain': root_domain,
        'record_id': record_id,
        'result': result,
    })
    status_code = 200 if result.get('success') else 400
    return jsonify(result), status_code


@root_domain_bp.route('/internal/dns/record/create', methods=['POST'])
def internal_create_dns_record():
    denied = _require_admin()
    if denied:
        return denied

    root_domain = request.form.get('root_domain', '').strip().lower()
    sub_domain = request.form.get('sub_domain', '').strip()
    record_type = request.form.get('record_type', '').strip()
    value = request.form.get('value', '').strip()
    ttl = request.form.get('ttl', '').strip() or '600'
    line = request.form.get('line', '').strip() or None

    if not all([root_domain, sub_domain, record_type, value]):
        return jsonify({'error': 'root_domain、sub_domain、record_type、value 必填'}), 400

    context, error_response, status = _get_dns_context(root_domain)
    if error_response:
        return error_response, status

    result = create_dns_record(
        root_domain,
        context['root']['dns_provider'],
        context['credential'],
        sub_domain,
        record_type,
        value,
        ttl=ttl,
        line=line,
    )
    log({
        'action': 'dns_create_record',
        'user': session.get('username'),
        'root_domain': root_domain,
        'sub_domain': sub_domain,
        'result': result,
    })
    status_code = 200 if result.get('success') else 400
    return jsonify(result), status_code


@root_domain_bp.route('/internal/dns/record/delete', methods=['POST'])
def internal_delete_dns_record():
    denied = _require_admin()
    if denied:
        return denied

    root_domain = request.form.get('root_domain', '').strip().lower()
    record_id = request.form.get('record_id', '').strip()
    if not root_domain or not record_id:
        return jsonify({'error': 'root_domain 和 record_id 必填'}), 400

    context, error_response, status = _get_dns_context(root_domain)
    if error_response:
        return error_response, status

    result = delete_dns_record(
        root_domain,
        context['root']['dns_provider'],
        context['credential'],
        record_id,
    )
    log({
        'action': 'dns_delete_record',
        'user': session.get('username'),
        'root_domain': root_domain,
        'record_id': record_id,
        'result': result,
    })
    status_code = 200 if result.get('success') else 400
    return jsonify(result), status_code
