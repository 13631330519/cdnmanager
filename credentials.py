from datetime import datetime
from flask import Blueprint, jsonify, request, session
from common import VALID_PROVIDERS
from models import load_credentials, upsert_credential, delete_credential, load_users

credential_bp = Blueprint('credential_bp', __name__)


def get_credential(provider, credential_id):
    if provider not in VALID_PROVIDERS:
        return None
    return next((c for c in load_credentials().get(provider, []) if c.get('id') == credential_id), None)


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
    access_key = request.form.get('access_key', '').strip()
    secret_key = request.form.get('secret_key', '').strip()
    if provider not in VALID_PROVIDERS:
        return jsonify({"error": "不支持的提供商"}), 400
    if not credential_id or not credential_name or not access_key or not secret_key:
        return jsonify({"error": "凭据ID、名称、AccessKey 和 SecretKey 都不能为空"}), 400


    message = "凭据已更新" if get_credential(provider, credential_id) else "凭据已添加"
    upsert_credential(provider, {
        'id': credential_id,
        'name': credential_name,
        'access_key': access_key,
        'secret_key': secret_key,
        'updated_at': datetime.now().isoformat() if get_credential(provider, credential_id) else None,
        'created_at': datetime.now().isoformat() if not get_credential(provider, credential_id) else get_credential(provider, credential_id).get('created_at')
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
