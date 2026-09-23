import json
import uuid
from datetime import datetime

from flask import Blueprint, jsonify, request

from cdnmanager.common import STORAGE_PROVIDERS
from cdnmanager.db import (
    delete_storage_target,
    get_storage_credential,
    get_storage_target,
    upsert_storage_target,
    get_environment, 
    get_project,
)
from cdnmanager.routes.common import require_admin
from cdnmanager.providers.storage.storage_service import ensure_browser_cors, get_adapter

storage_target_bp = Blueprint('storage_target_bp', __name__)


def _parse_binding(project_id, environment_id):
    project_id = (project_id or '').strip() or None
    environment_id = (environment_id or '').strip() or None
    if environment_id and not project_id:
        environment = get_environment(environment_id)
        if environment:
            project_id = environment['project_id']
    if project_id and not get_project(project_id):
        project_id = None
        environment_id = None
    if environment_id:
        environment = get_environment(environment_id)
        if not environment or environment['project_id'] != project_id:
            environment_id = None
    return project_id, environment_id


@storage_target_bp.route('/save_storage_target', methods=['POST'])
def save_storage_target_route():
    denied = require_admin()
    if denied:
        return denied

    target_id = request.form.get('target_id', '').strip() or uuid.uuid4().hex[:16]
    name = request.form.get('name', '').strip()
    provider = request.form.get('provider', '').strip()
    credential_id = request.form.get('credential_id', '').strip()
    bucket = request.form.get('bucket', '').strip()
    region = request.form.get('region', '').strip()
    endpoint = request.form.get('endpoint', '').strip()
    allow_user_delete = request.form.get('allow_user_delete') == '1'
    project_id, environment_id = _parse_binding(
        request.form.get('project_id'),
        request.form.get('environment_id'),
    )

    if provider not in STORAGE_PROVIDERS:
        return jsonify({'error': '不支持的存储类型'}), 400
    if not name or not credential_id or not bucket or not region:
        return jsonify({'error': '名称、凭据、bucket、region 必填'}), 400
    if not project_id or not environment_id:
        return jsonify({'error': '存储目标必须绑定项目和环境'}), 400

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
            'endpoint': endpoint,
        },
        'cdn_domain': None,
        'project_id': project_id,
        'environment_id': environment_id,
        'allow_user_delete': allow_user_delete,
        'created_at': existing.get('created_at') if existing else datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat(),
    })
    message = '存储目标已更新' if existing else '存储目标已添加'
    cors_warning = None
    try:
        adapter = get_adapter(provider)
        ensure_browser_cors(adapter, credential, {
            'bucket': bucket,
            'region': region,
            'endpoint': endpoint,
        }, ['*'])
        message += '，已尝试配置 Bucket CORS'
    except Exception as exc:
        hint = ''
        if provider == 'cos':
            hint = '（腾讯云需授予 name/cos:GetBucketCORS 与 name/cos:PutBucketCORS，或在控制台手动配置跨域）'
        cors_warning = f'Bucket CORS 自动配置失败，请手动配置{hint}：{exc}'

    payload = {'success': True, 'message': message, 'target_id': target_id}
    if cors_warning:
        payload['cors_warning'] = cors_warning
    return jsonify(payload)


@storage_target_bp.route('/delete_storage_target', methods=['POST'])
def delete_storage_target_route():
    denied = require_admin()
    if denied:
        return denied
    target_id = request.form.get('target_id', '').strip()
    if not target_id:
        return jsonify({'error': 'target_id 必填'}), 400
    delete_storage_target(target_id)
    return jsonify({'success': True, 'message': '存储目标已删除'})
