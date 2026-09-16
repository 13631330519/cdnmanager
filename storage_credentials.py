from datetime import datetime

from flask import Blueprint, jsonify, request, session

from common import STORAGE_CREDENTIAL_FIELD_LABELS, STORAGE_PROVIDERS
from models import delete_storage_credential, get_storage_credential, get_user, upsert_storage_credential

storage_credential_bp = Blueprint('storage_credential_bp', __name__)


def _require_admin():
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401
    user = get_user(session['username'])
    if not user or user.get('role') != 'admin':
        return jsonify({'error': '无权限'}), 403
    return None


def _validate_fields(provider, form):
    fields = STORAGE_CREDENTIAL_FIELD_LABELS.get(provider, [])
    values = {}
    for field in fields:
        value = form.get(field['name'], '').strip()
        if not value:
            return None, jsonify({'error': f"{field['label']} 不能为空"}), 400
        values[field['name']] = value
    return values, None, None


@storage_credential_bp.route('/save_storage_credential', methods=['POST'])
def save_storage_credential_route():
    denied = _require_admin()
    if denied:
        return denied

    provider = request.form.get('provider')
    credential_id = request.form.get('credential_id', '').strip()
    credential_name = request.form.get('credential_name', '').strip()
    if provider not in STORAGE_PROVIDERS:
        return jsonify({'error': '不支持的存储类型'}), 400
    if not credential_id or not credential_name:
        return jsonify({'error': '凭据ID 和名称不能为空'}), 400

    values, error_response, status = _validate_fields(provider, request.form)
    if error_response:
        return error_response, status

    existing = get_storage_credential(provider, credential_id)
    upsert_storage_credential(provider, {
        'id': credential_id,
        'name': credential_name,
        'access_key': values.get('access_key'),
        'secret_key': values.get('secret_key'),
        'created_at': existing.get('created_at') if existing else datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat(),
    })
    message = '存储凭据已更新' if existing else '存储凭据已添加'
    return jsonify({'success': True, 'message': message})


@storage_credential_bp.route('/delete_storage_credential', methods=['POST'])
def delete_storage_credential_route():
    denied = _require_admin()
    if denied:
        return denied
    provider = request.form.get('provider')
    credential_id = request.form.get('credential_id', '').strip()
    if provider not in STORAGE_PROVIDERS or not credential_id:
        return jsonify({'error': '参数非法'}), 400
    delete_storage_credential(provider, credential_id)
    return jsonify({'success': True, 'message': '存储凭据已删除'})
