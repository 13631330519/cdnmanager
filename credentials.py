from datetime import datetime
from flask import Blueprint, jsonify, request, session
from common import VALID_PROVIDERS, CREDENTIAL_FIELD_LABELS
from models import load_credentials, upsert_credential, delete_credential, load_users, get_credential

credential_bp = Blueprint('credential_bp', __name__)


def get_credential(provider, credential_id):
    if provider not in VALID_PROVIDERS:
        return None
    return next((c for c in load_credentials().get(provider, []) if c.get('id') == credential_id), None)


def _validate_credential_fields(provider, form):
    fields = CREDENTIAL_FIELD_LABELS.get(provider, [])
    values = {}
    for field in fields:
        name = field['name']
        value = form.get(name, '').strip()
        if not value:
            return None, jsonify({"error": f"{field['label']} 不能为空"}), 400
        values[name] = value
    return values, None, None


@credential_bp.route('/save_credential', methods=['POST'])
def save_credential_route():
    if 'username' not in session:
        return jsonify({"error": "未登录"}), 401
    user = next((u for u in load_users() if u['username'] == session['username']), None)
    if user['role'] != 'admin':
        return jsonify({"error": "无权限保存凭据"}), 403

    provider = request.form.get('provider')
    credential_id = request.form.get('credential_id', '').strip()
    credential_name = request.form.get('credential_name', '').strip()
    if provider not in VALID_PROVIDERS:
        return jsonify({"error": "不支持的提供商"}), 400
    if not credential_id or not credential_name:
        return jsonify({"error": "凭据ID 和名称不能为空"}), 400

    values, error_response, status = _validate_credential_fields(provider, request.form)
    if error_response:
        return error_response, status

    existing = get_credential(provider, credential_id)
    message = "凭据已更新" if existing else "凭据已添加"
    upsert_credential(provider, {
        'id': credential_id,
        'name': credential_name,
        'access_key': values.get('access_key'),
        'secret_key': values.get('secret_key'),
        'extra_key': values.get('extra_key'),
        'extra_secret': values.get('extra_secret'),
        'updated_at': datetime.now().isoformat() if existing else None,
        'created_at': existing.get('created_at') if existing else datetime.now().isoformat(),
    })
    return jsonify({"success": True, "message": message})


@credential_bp.route('/delete_credential', methods=['POST'])
def delete_credential_route():
    if 'username' not in session:
        return jsonify({"error": "未登录"}), 401
    user = next((u for u in load_users() if u['username'] == session['username']), None)
    if user['role'] != 'admin':
        return jsonify({"error": "无权限删除凭据"}), 403
    provider = request.form.get('provider')
    credential_id = request.form.get('credential_id', '').strip()
    if provider not in VALID_PROVIDERS or not credential_id:
        return jsonify({"error": "参数非法"}), 400

    delete_credential(provider, credential_id)
    return jsonify({"success": True, "message": "凭据已删除"})
