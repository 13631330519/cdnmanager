import json
from datetime import datetime
from flask import Blueprint, jsonify, request, session
from common import CREDENTIALS_FILE, VALID_PROVIDERS
from users import load_users

credential_bp = Blueprint('credential_bp', __name__)


def load_credentials():
    with open(CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    for provider in VALID_PROVIDERS:
        data.setdefault(provider, [])
    return data


def save_credentials(credentials):
    with open(CREDENTIALS_FILE, 'w', encoding='utf-8') as f:
        json.dump(credentials, f, indent=2, ensure_ascii=False)


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
    credentials = load_credentials()
    provider_list = credentials.setdefault(provider, [])
    existing = next((c for c in provider_list if c.get('id') == credential_id), None)
    if existing:
        existing.update({
            "name": credential_name,
            "access_key": access_key,
            "secret_key": secret_key,
            "updated_at": datetime.now().isoformat()
        })
        message = "凭据已更新"
    else:
        provider_list.append({
            "id": credential_id,
            "name": credential_name,
            "access_key": access_key,
            "secret_key": secret_key,
            "created_at": datetime.now().isoformat()
        })
        message = "凭据已添加"
    save_credentials(credentials)
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
    credentials = load_credentials()
    credentials[provider] = [c for c in credentials.get(provider, []) if c.get('id') != credential_id]
    save_credentials(credentials)
    return jsonify({"success": True, "message": "凭据已删除"})
