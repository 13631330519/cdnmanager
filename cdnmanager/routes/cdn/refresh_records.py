from flask import Blueprint, jsonify, request

from cdnmanager.common import PROVIDER_LABELS
from cdnmanager.db import get_visible_domains, load_url_records
from cdnmanager.routes.common import get_session_user, require_login

refresh_records_bp = Blueprint('refresh_records_bp', __name__)


@refresh_records_bp.route('/api/refresh_records', methods=['GET'])
def api_refresh_records():
    login_error = require_login()
    if login_error is not None:
        return login_error
    user = get_session_user()
    if not user:
        return jsonify({'error': '用户不存在'}), 404

    domain = request.args.get('domain', '').strip() or None
    project_id = request.args.get('project_id', '').strip() or None
    environment_id = request.args.get('environment_id', '').strip() or None
    visible_domains = get_visible_domains(user['username'], user.get('role'))
    visible = {item['domain'] for item in visible_domains}
    domain_meta = {item['domain']: item for item in visible_domains}

    if domain and domain not in visible:
        return jsonify({'error': '无权限查看该域名'}), 403

    records = load_url_records(domain=domain)
    if not domain:
        records = [row for row in records if row.get('domain') in visible]

    if project_id:
        records = [
            row for row in records
            if domain_meta.get(row.get('domain'), {}).get('project_id') == project_id
        ]
    if environment_id:
        records = [
            row for row in records
            if domain_meta.get(row.get('domain'), {}).get('environment_id') == environment_id
        ]

    for row in records:
        row['provider_label'] = PROVIDER_LABELS.get(row.get('provider'), row.get('provider'))
        meta = domain_meta.get(row.get('domain'), {})
        row['project_id'] = meta.get('project_id')
        row['environment_id'] = meta.get('environment_id')

    return jsonify({
        'success': True,
        'records': records,
        'domain': domain,
        'project_id': project_id,
        'environment_id': environment_id,
    })
