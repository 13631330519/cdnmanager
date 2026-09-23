from datetime import datetime
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request

from cdnmanager.common import (
    UPLOAD_BATCH_INIT_SIZE,
    UPLOAD_FILE_COMPLETED,
    UPLOAD_FILE_FAILED,
    UPLOAD_FILE_VERIFYING,
    UPLOAD_PRESIGN_BATCH_MAX,
    REFRESH_STATUS_NONE,
)
from cdnmanager.db import (
    find_bound_domain,
    get_credential,
    get_upload_file,
    get_upload_job,
    list_upload_parts,
    recalculate_upload_job_stats,
    update_upload_file,
    get_domain,
    get_url_by_id,
    load_urls,
    resolve_storage_target_for_domain,
)
from cdnmanager.providers.storage.storage_service import uses_multipart
from cdnmanager.services.storage_refresh_service import refresh_file_for_target
from cdnmanager.services.api_auth_service import (
    verify_domain_job_signature,
    verify_domain_signature,
)
from cdnmanager.services.refresh_service import record_url_refresh, submit_refresh
from cdnmanager.services.upload_service import (
    create_upload_job_shell,
    presign_put_batch,
    verify_multipart_parts,
)

external_bp = Blueprint('external_bp', __name__)


def _api_user(domain_name):
    return f'api:{domain_name}'


def _verify_job_request(domain_record, job_id, data):
    signature = data.get('signature')
    if not data.get('timestamp') or not signature:
        return False, 'timestamp/signature 均为必填字段'
    return verify_domain_job_signature(domain_record, job_id, data.get('timestamp'), signature)


@external_bp.route('/api/task_status', methods=['GET'])
def api_task_status():
    domain = request.args.get('domain')
    url_idx = request.args.get('url_idx')
    if not domain and not url_idx:
        return jsonify({"success": False, "error": "domain 或 url_idx 参数必填"}), 400

    if domain:
        target = get_domain(domain)
        if not target:
            return jsonify({"success": False, "error": "域名不存在"}), 404

        return jsonify({
            "success": True,
            "domain": target['domain'],
            "provider": target.get('provider'),
            "refresh_status": target.get('refresh_status', REFRESH_STATUS_NONE),
            "last_refreshed_at": target.get('last_refreshed_at'),
            "task_id": target.get('task_id'),
            "task_status": target.get('refresh_task_status'),
            "status_detail": target.get('refresh_task_detail')
        })

    if url_idx is not None:
        try:
            url_id = int(url_idx)
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "url_idx 格式不正确"}), 400
        target = get_url_by_id(url_id)
    else:
        url = request.args.get('url')
        if not url:
            return jsonify({"success": False, "error": "url 或 url_idx 必填"}), 400
        target = next((u for u in load_urls() if u.get('url') == url), None)

    if not target:
        return jsonify({"success": False, "error": "URL 记录不存在"}), 404

    return jsonify({
        "success": True,
        "url": target.get('url'),
        "provider": target.get('provider'),
        "refresh_status": target.get('refresh_status', REFRESH_STATUS_NONE),
        "submitted_at": target.get('submitted_at'),
        "completed_at": target.get('completed_at'),
        "task_id": target.get('task_id'),
        "status_detail": target.get('refresh_task_detail')
    })


@external_bp.route('/api/refresh_url', methods=['POST'])
def api_refresh_url():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "请求体必须为JSON"}), 400

    url = data.get('url')
    timestamp = data.get('timestamp')
    signature = data.get('signature')

    if not url or not timestamp or not signature:
        return jsonify({"success": False, "error": "url/timestamp/signature 均为必填字段"}), 400

    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return jsonify({"success": False, "error": "URL 域名解析失败"}), 400

    domain_record = find_bound_domain(host)
    if not domain_record:
        return jsonify({"success": False, "error": "未找到对应的已绑定域名"}), 404

    message = f"{url}{timestamp}"
    ok, error = verify_domain_signature(domain_record, message, timestamp, signature)
    if not ok:
        return jsonify({"success": False, "error": error}), 403 if error == '验签失败' or 'Key' in (error or '') else 400

    provider = domain_record.get('provider')
    credential_id = domain_record.get('credential_id')
    credential = get_credential(provider, credential_id)
    if not credential:
        return jsonify({"success": False, "error": "域名绑定的凭据不存在或已删除"}), 400

    result = submit_refresh(
        provider,
        domain_record['domain'],
        credential,
        url=url,
        cpcode=domain_record.get('cpcode'),
    )
    if result.get('error') and not result.get('success'):
        return jsonify({"success": False, "error": result.get('error', '刷新失败')}), 400

    record_url_refresh(domain_record['domain'], provider, credential_id, result, url)
    return jsonify(result)


@external_bp.route('/api/upload/init', methods=['POST'])
def api_upload_init():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'success': False, 'error': '请求体必须为JSON'}), 400

    domain_name = (data.get('domain') or '').strip().lower()
    timestamp = data.get('timestamp')
    signature = data.get('signature')
    files = data.get('files') or []
    remote_prefix = (data.get('remote_prefix') or '').strip()
    storage_target_id = (data.get('storage_target_id') or '').strip() or None
    refresh_after = 1 if data.get('refresh_after') else 0

    if not domain_name or not timestamp or not signature:
        return jsonify({'success': False, 'error': 'domain/timestamp/signature 均为必填'}), 400
    if not files:
        return jsonify({'success': False, 'error': 'files 不能为空'}), 400
    if len(files) > UPLOAD_BATCH_INIT_SIZE:
        return jsonify({'success': False, 'error': f'首批最多 {UPLOAD_BATCH_INIT_SIZE} 个文件'}), 400

    domain_record = get_domain(domain_name)
    if not domain_record:
        domain_record = find_bound_domain(domain_name)
    if not domain_record:
        return jsonify({'success': False, 'error': '域名不存在'}), 404

    message = f"{domain_record['domain']}{timestamp}"
    ok, error = verify_domain_signature(domain_record, message, timestamp, signature)
    if not ok:
        return jsonify({'success': False, 'error': error}), 403 if error in {'验签失败'} or (error and 'Key' in error) else 400

    target, target_error = resolve_storage_target_for_domain(domain_record, storage_target_id)
    if target_error:
        return jsonify({'success': False, 'error': target_error}), 400

    api_user = {'username': _api_user(domain_record['domain'])}
    try:
        job_id, rows, _ = create_upload_job_shell(
            api_user, target['id'], remote_prefix, refresh_after, first_batch=files,
        )
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400

    presign_ids = [row['id'] for row in rows if not uses_multipart(row['size'])]
    presigned, presign_errors = presign_put_batch(presign_ids[:UPLOAD_PRESIGN_BATCH_MAX]) if presign_ids else ([], [])

    return jsonify({
        'success': True,
        'job_id': job_id,
        'domain': domain_record['domain'],
        'storage_target_id': target['id'],
        'files': [
            {
                'id': row['id'],
                'relative_path': row['relative_path'],
                'size': row['size'],
                'multipart': uses_multipart(row['size']),
            }
            for row in rows
        ],
        'presigned': presigned,
        'presign_errors': presign_errors,
    })


@external_bp.route('/api/upload/presign', methods=['POST'])
def api_upload_presign():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'success': False, 'error': '请求体必须为JSON'}), 400

    domain_name = (data.get('domain') or '').strip().lower()
    job_id = (data.get('job_id') or '').strip()
    file_ids = data.get('file_ids') or []

    if not domain_name or not job_id or not file_ids:
        return jsonify({'success': False, 'error': 'domain/job_id/file_ids 必填'}), 400
    if len(file_ids) > UPLOAD_PRESIGN_BATCH_MAX:
        return jsonify({'success': False, 'error': f'单次最多 {UPLOAD_PRESIGN_BATCH_MAX} 个'}), 400

    domain_record = get_domain(domain_name) or find_bound_domain(domain_name)
    if not domain_record:
        return jsonify({'success': False, 'error': '域名不存在'}), 404

    ok, error = _verify_job_request(domain_record, job_id, data)
    if not ok:
        return jsonify({'success': False, 'error': error}), 403 if error == '验签失败' else 400

    job = get_upload_job(job_id)
    if not job or job['username'] != _api_user(domain_record['domain']):
        return jsonify({'success': False, 'error': 'Job 不存在或无权限'}), 404

    for file_id in file_ids:
        file_record = get_upload_file(file_id)
        if not file_record or file_record['job_id'] != job_id:
            return jsonify({'success': False, 'error': f'文件不存在: {file_id}'}), 404

    results, errors = presign_put_batch(file_ids)
    return jsonify({'success': True, 'files': results, 'errors': errors})


@external_bp.route('/api/upload/complete', methods=['POST'])
def api_upload_complete():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'success': False, 'error': '请求体必须为JSON'}), 400

    domain_name = (data.get('domain') or '').strip().lower()
    job_id = (data.get('job_id') or '').strip()
    file_id = (data.get('file_id') or '').strip()
    etag = (data.get('etag') or '').strip().strip('"')

    if not domain_name or not job_id or not file_id:
        return jsonify({'success': False, 'error': 'domain/job_id/file_id 必填'}), 400

    domain_record = get_domain(domain_name) or find_bound_domain(domain_name)
    if not domain_record:
        return jsonify({'success': False, 'error': '域名不存在'}), 404

    ok, error = _verify_job_request(domain_record, job_id, data)
    if not ok:
        return jsonify({'success': False, 'error': error}), 403 if error == '验签失败' else 400

    file_record = get_upload_file(file_id)
    if not file_record or file_record['job_id'] != job_id:
        return jsonify({'success': False, 'error': '文件任务不存在'}), 404

    job = get_upload_job(job_id)
    if not job or job['username'] != _api_user(domain_record['domain']):
        return jsonify({'success': False, 'error': 'Job 无权限'}), 403

    from cdnmanager.routes.storage.uploads import _maybe_cleanup_job
    from cdnmanager.providers.storage.storage_service import total_parts_for
    from cdnmanager.services.upload_service import _job_storage_ctx

    try:
        target, credential, config, adapter = _job_storage_ctx(job)
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400

    update_upload_file(file_id, {'status': UPLOAD_FILE_VERIFYING})

    if file_record.get('upload_id'):
        expected_parts = total_parts_for(file_record['size'])
        local_parts = [
            {'part_number': part['part_number'], 'etag': part['etag']}
            for part in list_upload_parts(file_id)
            if part.get('status') == 'completed' and part.get('etag')
        ]
        parts, verify_err = verify_multipart_parts(
            adapter, credential, config, file_record, local_parts,
        )
        if verify_err or not parts:
            update_upload_file(file_id, {
                'status': UPLOAD_FILE_FAILED,
                'error': verify_err or '分片校验失败',
                'finished_at': datetime.now().isoformat(),
            })
            recalculate_upload_job_stats(job_id)
            _maybe_cleanup_job(job_id)
            return jsonify({'success': False, 'error': verify_err or '分片校验失败'}), 400
        try:
            etag = adapter.complete_multipart(
                credential, config, file_record['storage_key'], file_record['upload_id'], parts,
            ) or etag
        except Exception as exc:
            update_upload_file(file_id, {
                'status': UPLOAD_FILE_FAILED,
                'error': str(exc),
                'finished_at': datetime.now().isoformat(),
            })
            recalculate_upload_job_stats(job_id)
            _maybe_cleanup_job(job_id)
            return jsonify({'success': False, 'error': str(exc)}), 400

    verify = adapter.verify_object(
        credential, config, file_record['storage_key'], file_record['size'],
    )
    if not verify.get('ok'):
        update_upload_file(file_id, {
            'status': UPLOAD_FILE_FAILED,
            'error': verify.get('error') or '校验失败',
            'finished_at': datetime.now().isoformat(),
        })
        recalculate_upload_job_stats(job_id)
        _maybe_cleanup_job(job_id)
        return jsonify({'success': False, 'error': verify.get('error')}), 400

    refresh_result = None
    public_url = None
    if job.get('refresh_after'):
        refresh_result = refresh_file_for_target(target, file_record['storage_key'])
        if refresh_result and refresh_result.get('results'):
            public_url = refresh_result['results'][0].get('url')

    update_upload_file(file_id, {
        'status': UPLOAD_FILE_COMPLETED,
        'bytes_uploaded': file_record['size'],
        'etag': verify.get('etag') or etag,
        'error': None,
        'finished_at': datetime.now().isoformat(),
        'last_heartbeat_at': datetime.now().isoformat(),
    })
    recalculate_upload_job_stats(job_id)
    _maybe_cleanup_job(job_id)

    return jsonify({
        'success': True,
        'etag': verify.get('etag') or etag,
        'public_url': public_url,
        'refresh': refresh_result,
    })
