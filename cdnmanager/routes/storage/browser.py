from flask import Blueprint, jsonify, request, session

from cdnmanager.common import can_storage_delete
from cdnmanager.db.models import get_storage_credential, get_storage_target, get_user
from cdnmanager.providers.storage_service import build_list_prefix, get_adapter

storage_browser_bp = Blueprint('storage_browser_bp', __name__)


def _require_login():
    if 'username' not in session:
        return None, jsonify({'error': '未登录'}), 401
    user = get_user(session['username'])
    if not user:
        return None, jsonify({'error': '用户不存在'}), 404
    return user, None, None


def _target_context(target_id):
    user, err, status = _require_login()
    if err:
        return None, None, None, err, status
    target = get_storage_target(target_id)
    if not target:
        return None, None, None, jsonify({'error': '存储目标不存在'}), 404
    credential = get_storage_credential(target['provider'], target['credential_id'])
    if not credential:
        return None, None, None, jsonify({'error': '存储凭据不存在'}), 400
    config = target.get('target_config') or {}
    adapter = get_adapter(target['provider'])
    return user, target, (credential, config, adapter), None, None


@storage_browser_bp.route('/api/storage/list', methods=['GET'])
def list_storage_objects():
    target_id = request.args.get('target_id', '').strip()
    remote_prefix = request.args.get('prefix', '').strip()
    if not target_id:
        return jsonify({'error': 'target_id 必填'}), 400

    user, target, ctx, err, status = _target_context(target_id)
    if err:
        return err, status
    credential, config, adapter = ctx

    list_prefix = build_list_prefix(config, remote_prefix)
    try:
        listing = adapter.list_objects(credential, config, prefix=list_prefix)
    except Exception as exc:
        return jsonify({'error': f'列举对象失败: {exc}'}), 400

    return jsonify({
        'success': True,
        'can_delete': can_storage_delete(user, target),
        'remote_prefix': remote_prefix,
        'list_prefix': list_prefix,
        'folders': listing.get('folders') or [],
        'files': listing.get('files') or [],
    })


@storage_browser_bp.route('/api/storage/download-urls', methods=['POST'])
def storage_download_urls():
    data = request.get_json(silent=True) or {}
    target_id = (data.get('target_id') or '').strip()
    keys = data.get('keys') or []
    if not target_id or not keys:
        return jsonify({'error': 'target_id 与 keys 必填'}), 400
    if len(keys) > 100:
        return jsonify({'error': '单次最多下载 100 个文件'}), 400

    _user, _target, ctx, err, status = _target_context(target_id)
    if err:
        return err, status
    credential, config, adapter = ctx

    urls = []
    for key in keys:
        try:
            urls.append({
                'key': key,
                'url': adapter.presign_get(credential, config, key),
            })
        except Exception as exc:
            return jsonify({'error': f'生成下载链接失败: {exc}'}), 400

    return jsonify({'success': True, 'urls': urls})


@storage_browser_bp.route('/api/storage/delete', methods=['POST'])
def storage_delete_objects():
    data = request.get_json(silent=True) or {}
    target_id = (data.get('target_id') or '').strip()
    keys = data.get('keys') or []
    prefixes = data.get('prefixes') or []
    if not target_id:
        return jsonify({'error': 'target_id 必填'}), 400
    if not keys and not prefixes:
        return jsonify({'error': 'keys 或 prefixes 必填'}), 400

    user, target, ctx, err, status = _target_context(target_id)
    if err:
        return err, status
    if not can_storage_delete(user, target):
        return jsonify({'error': '无删除权限'}), 403

    credential, config, adapter = ctx
    deleted_files = 0
    deleted_folders = 0
    try:
        if keys:
            deleted_files = adapter.delete_objects(credential, config, keys)
        for prefix in prefixes:
            deleted_folders += adapter.delete_prefix(credential, config, prefix)
    except Exception as exc:
        return jsonify({'error': f'删除失败: {exc}'}), 400

    return jsonify({
        'success': True,
        'deleted_files': deleted_files,
        'deleted_folders': deleted_folders,
    })
