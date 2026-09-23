from urllib.parse import quote

from flask import Blueprint, jsonify, request

from cdnmanager.common import can_storage_delete
from cdnmanager.db import get_storage_credential, get_storage_target
from cdnmanager.providers.storage.storage_service import build_list_prefix, get_adapter
from cdnmanager.routes.common import get_session_user, require_login

storage_browser_bp = Blueprint('storage_browser_bp', __name__)


def _require_login():
    login_error = require_login()
    if login_error is not None:
        return None, login_error[0], login_error[1]
    user = get_session_user()
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

    _user, target, ctx, err, status = _target_context(target_id)
    if err:
        return err, status
    credential, config, adapter = ctx

    urls = []
    for key in keys:
        try:
            if target['provider'] in {'ftp', 'sftp', 'ftps'}:
                url = f"/api/storage/proxy-download?target_id={quote(target_id)}&key={quote(key)}"
            else:
                url = adapter.presign_get(credential, config, key)
            urls.append({
                'key': key,
                'url': url,
            })
        except Exception as exc:
            return jsonify({'error': f'生成下载链接失败: {exc}'}), 400

    return jsonify({'success': True, 'urls': urls})


@storage_browser_bp.route('/api/storage/proxy-download', methods=['GET'])
def storage_proxy_download():
    target_id = request.args.get('target_id', '').strip()
    key = request.args.get('key', '').strip()
    if not target_id or not key:
        return jsonify({'error': 'target_id 与 key 必填'}), 400

    _user, target, ctx, err, status = _target_context(target_id)
    if err:
        return err, status
    if target['provider'] not in {'ftp', 'sftp', 'ftps'}:
        return jsonify({'error': '仅对 FTP/SFTP/FTPS 目标开放代理下载'}), 400

    credential, config, adapter = ctx
    range_header = request.headers.get('Range')
    return adapter.stream_download(credential, config, key, range_header=range_header)


@storage_browser_bp.route('/api/storage/upload', methods=['POST'])
def storage_upload_objects():
    target_id = request.form.get('target_id', '').strip()
    remote_prefix = request.form.get('prefix', '').strip()
    resume_from = int(request.form.get('resume_from', '0') or '0')
    if not target_id:
        return jsonify({'error': 'target_id 必填'}), 400
    if 'file' not in request.files:
        return jsonify({'error': 'file 必填'}), 400

    user, target, ctx, err, status = _target_context(target_id)
    if err:
        return err, status
    if target['provider'] not in {'ftp', 'sftp', 'ftps'}:
        return jsonify({'error': '仅对 FTP/SFTP/FTPS 目标开放代理上传'}), 400

    credential, config, adapter = ctx
    uploaded = request.files['file']
    try:
        result = adapter.upload_file(credential, config, remote_prefix, uploaded, resume_from=resume_from)
    except Exception as exc:
        return jsonify({'error': f'上传失败: {exc}'}), 400
    return jsonify({'success': True, 'result': result})


@storage_browser_bp.route('/api/storage/mkdir', methods=['POST'])
def storage_mkdir():
    data = request.get_json(silent=True) or {}
    target_id = (data.get('target_id') or '').strip()
    directory_name = (data.get('directory_name') or '').strip()
    if not target_id or not directory_name:
        return jsonify({'error': 'target_id 与 directory_name 必填'}), 400

    user, target, ctx, err, status = _target_context(target_id)
    if err:
        return err, status
    if not can_storage_delete(user, target):
        return jsonify({'error': '无创建权限'}), 403
    if target['provider'] not in {'ftp', 'sftp', 'ftps'}:
        return jsonify({'error': '仅对 FTP/SFTP/FTPS 目标开放目录创建'}), 400

    credential, config, adapter = ctx
    try:
        result = adapter.mkdir(credential, config, directory_name)
    except Exception as exc:
        return jsonify({'error': f'新建目录失败: {exc}'}), 400
    return jsonify({'success': True, 'result': result})


@storage_browser_bp.route('/api/storage/rename', methods=['POST'])
def storage_rename():
    data = request.get_json(silent=True) or {}
    target_id = (data.get('target_id') or '').strip()
    old_key = (data.get('old_key') or '').strip()
    new_name = (data.get('new_name') or '').strip()
    if not target_id or not old_key or not new_name:
        return jsonify({'error': 'target_id、old_key、new_name 必填'}), 400

    user, target, ctx, err, status = _target_context(target_id)
    if err:
        return err, status
    if not can_storage_delete(user, target):
        return jsonify({'error': '无重命名权限'}), 403
    if target['provider'] not in {'ftp', 'sftp', 'ftps'}:
        return jsonify({'error': '仅对 FTP/SFTP/FTPS 目标开放重命名'}), 400

    credential, config, adapter = ctx
    try:
        result = adapter.rename(credential, config, old_key, new_name)
    except Exception as exc:
        return jsonify({'error': f'重命名失败: {exc}'}), 400
    return jsonify({'success': True, 'result': result})


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
