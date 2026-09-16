import json
import uuid
from datetime import datetime

from flask import Blueprint, jsonify, request, session

from common import STORAGE_PROVIDERS
from models import (
    delete_storage_target,
    get_storage_credential,
    get_storage_target,
    get_user,
    upsert_storage_target,
)

storage_target_bp = Blueprint('storage_target_bp', __name__)


def _require_admin():
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401
    user = get_user(session['username'])
    if not user or user.get('role') != 'admin':
        return jsonify({'error': '无权限'}), 403
    return None


def _parse_target_config(raw):
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return {}


@storage_target_bp.route('/save_storage_target', methods=['POST'])
def save_storage_target_route():
    denied = _require_admin()
    if denied:
        return denied

    target_id = request.form.get('target_id', '').strip() or uuid.uuid4().hex[:16]
    name = request.form.get('name', '').strip()
    provider = request.form.get('provider', '').strip()
    credential_id = request.form.get('credential_id', '').strip()
    bucket = request.form.get('bucket', '').strip()
    region = request.form.get('region', '').strip()
    base_path = request.form.get('base_path', '').strip()
    public_base_url = request.form.get('public_base_url', '').strip()
    endpoint = request.form.get('endpoint', '').strip()
    cdn_domain = request.form.get('cdn_domain', '').strip() or None

    if provider not in STORAGE_PROVIDERS:
        return jsonify({'error': '不支持的存储类型'}), 400
    if not name or not credential_id or not bucket or not region:
        return jsonify({'error': '名称、凭据、bucket、region 必填'}), 400

    credential = get_storage_credential(provider, credential_id)
    if not credential:
        return jsonify({'error': '存储凭据不存在'}), 400

    existing = get_storage_target(target_id)
    upsert_storage_target({
        'id': target_id,
        'name': name,
        'provider': provider,
        'credential_id': credential_id,
        'target_config': {
            'bucket': bucket,
            'region': region,
            'base_path': base_path,
            'public_base_url': public_base_url,
            'endpoint': endpoint,
        },
        'cdn_domain': cdn_domain,
        'created_at': existing.get('created_at') if existing else datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat(),
    })
    message = '存储目标已更新' if existing else '存储目标已添加'
    return jsonify({'success': True, 'message': message, 'target_id': target_id})


@storage_target_bp.route('/delete_storage_target', methods=['POST'])
def delete_storage_target_route():
    denied = _require_admin()
    if denied:
        return denied
    target_id = request.form.get('target_id', '').strip()
    if not target_id:
        return jsonify({'error': 'target_id 必填'}), 400
    delete_storage_target(target_id)
    return jsonify({'success': True, 'message': '存储目标已删除'})
