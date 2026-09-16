import uuid
from datetime import datetime

import logging

from flask import Blueprint, jsonify, request, session

from common import (
    UPLOAD_FILE_COMPLETED,
    UPLOAD_FILE_FAILED,
    UPLOAD_FILE_PENDING,
    UPLOAD_FILE_UPLOADING,
    UPLOAD_FILE_VERIFYING,
    UPLOAD_JOB_PENDING,
    UPLOAD_JOB_RUNNING,
    UPLOAD_PART_SIZE,
)
from credentials import get_credential
from domains import find_bound_domain, record_refresh_submission
from models import (
    cleanup_finished_upload_job,
    delete_upload_job_cascade,
    count_upload_files,
    get_storage_credential,
    get_storage_target,
    get_upload_file,
    get_upload_job,
    get_user,
    insert_upload_files,
    insert_upload_job,
    insert_upload_parts,
    list_upload_files,
    list_upload_parts,
    recalculate_upload_job_stats,
    update_upload_file,
    update_upload_job,
    update_upload_part,
)
from providers.akamai import refresh_akamai
from providers.alicdn import refresh_alicdn
from providers.ctyun import refresh_ctyun
from providers.lingzhi import refresh_lingzhi
from providers.storage_service import (
    build_object_key,
    build_public_url,
    ensure_browser_cors,
    get_adapter,
    part_size_for,
    total_parts_for,
    uses_multipart,
)

logger = logging.getLogger(__name__)
from providers.tencent import refresh_tencentcdn
from providers.volcengine import refresh_volcengine
from providers.x7host import refresh_x7host

upload_bp = Blueprint('upload_bp', __name__)


def _maybe_cleanup_job(job_id):
    try:
        cleanup_finished_upload_job(job_id)
    except Exception as exc:
        logger.warning('清理上传 Job 失败 %s: %s', job_id, exc)


def _require_login():
    if 'username' not in session:
        return None, jsonify({'error': '未登录'}), 401
    user = get_user(session['username'])
    if not user:
        return None, jsonify({'error': '用户不存在'}), 404
    return user, None, None


def _job_context(file_record):
    job = get_upload_job(file_record['job_id'])
    if not job:
        return None, None, None, jsonify({'error': 'Job 不存在'}), 404
    user, err, status = _require_login()
    if err:
        return None, None, None, err, status
    if job['username'] != user['username'] and user.get('role') != 'admin':
        return None, None, None, jsonify({'error': '无权限'}), 403
    target = get_storage_target(job['storage_target_id'])
    if not target:
        return None, None, None, jsonify({'error': '存储目标不存在'}), 404
    credential = get_storage_credential(target['provider'], target['credential_id'])
    if not credential:
        return None, None, None, jsonify({'error': '存储凭据不存在'}), 400
    config = target.get('target_config') or {}
    adapter = get_adapter(target['provider'])
    return job, target, (credential, config, adapter), None, None


def _refresh_uploaded_url(cdn_domain, public_url):
    if not cdn_domain or not public_url:
        return None
    domain_record = find_bound_domain(cdn_domain)
    if not domain_record and cdn_domain:
        domain_record = find_bound_domain(public_url.split('/')[2] if '://' in public_url else cdn_domain)
    if not domain_record:
        return {'success': False, 'error': '未找到绑定的 CDN 域名'}
    provider = domain_record.get('provider')
    credential = get_credential(provider, domain_record.get('credential_id'))
    if not credential:
        return {'success': False, 'error': 'CDN 凭据不存在'}
    if provider == 'alicdn':
        result = refresh_alicdn(domain_record['domain'], credential, url=public_url)
    elif provider == 'tencent':
        result = refresh_tencentcdn(domain_record['domain'], credential, url=public_url)
    elif provider == 'lingzhi':
        result = refresh_lingzhi(domain_record['domain'], credential, url=public_url)
    elif provider == 'akamai':
        result = refresh_akamai(domain_record['domain'], credential, url=public_url)
    elif provider == 'ctyun':
        result = refresh_ctyun(domain_record['domain'], credential, url=public_url)
    elif provider == 'volcengine':
        result = refresh_volcengine(domain_record['domain'], credential, url=public_url)
    elif provider == 'x7host':
        result = refresh_x7host(domain_record['domain'], credential, url=public_url)
    else:
        return {'success': False, 'error': '不支持的 CDN 提供商'}
    record_refresh_submission(domain_record['domain'], result)
    return result


@upload_bp.route('/api/upload/jobs', methods=['POST'])
def create_upload_job():
    user, err, status = _require_login()
    if err:
        return err, status

    data = request.get_json(silent=True) or {}
    storage_target_id = (data.get('storage_target_id') or '').strip()
    remote_prefix = (data.get('remote_prefix') or '').strip()
    refresh_after = 1 if data.get('refresh_after') else 0
    files = data.get('files') or []

    if not storage_target_id:
        return jsonify({'error': 'storage_target_id 必填'}), 400
    if not files:
        return jsonify({'error': 'files 不能为空'}), 400
    if len(files) > 2000:
        return jsonify({'error': 'Phase 1 单次最多 2000 个文件，更大批次请等待 Phase 2 分批 init'}), 400

    target = get_storage_target(storage_target_id)
    if not target:
        return jsonify({'error': '存储目标不存在'}), 404

    job_id = uuid.uuid4().hex[:16]
    total_bytes = 0
    upload_file_rows = []
    for item in files:
        relative_path = (item.get('relative_path') or item.get('path') or '').replace('\\', '/').lstrip('/')
        if not relative_path:
            return jsonify({'error': 'files.relative_path 必填'}), 400
        size = int(item.get('size') or 0)
        if size < 0:
            return jsonify({'error': 'files.size 非法'}), 400
        total_bytes += size
        file_id = uuid.uuid4().hex[:16]
        storage_key = build_object_key(
            target.get('target_config') or {},
            remote_prefix,
            relative_path,
        )
        upload_file_rows.append({
            'id': file_id,
            'job_id': job_id,
            'relative_path': relative_path,
            'size': size,
            'mime': item.get('mime') or 'application/octet-stream',
            'status': UPLOAD_FILE_PENDING,
            'bytes_uploaded': 0,
            'storage_key': storage_key,
            'upload_id': None,
            'etag': None,
            'error': None,
            'retry_count': 0,
            'started_at': None,
            'finished_at': None,
        })

    insert_upload_job({
        'id': job_id,
        'username': user['username'],
        'storage_target_id': storage_target_id,
        'remote_prefix': remote_prefix,
        'status': UPLOAD_JOB_PENDING,
        'total_files': len(upload_file_rows),
        'total_bytes': total_bytes,
        'done_files': 0,
        'done_bytes': 0,
        'failed_files': 0,
        'refresh_after': refresh_after,
        'created_at': datetime.now().isoformat(),
        'finished_at': None,
    })
    insert_upload_files(upload_file_rows)

    return jsonify({
        'success': True,
        'job_id': job_id,
        'files': [{'id': row['id'], 'relative_path': row['relative_path'], 'size': row['size']} for row in upload_file_rows],
    })


@upload_bp.route('/api/upload/jobs/<job_id>', methods=['GET'])
def get_upload_job_route(job_id):
    user, err, status = _require_login()
    if err:
        return err, status
    job = get_upload_job(job_id)
    if not job:
        return jsonify({'error': 'Job 不存在'}), 404
    if job['username'] != user['username'] and user.get('role') != 'admin':
        return jsonify({'error': '无权限'}), 403
    return jsonify({'success': True, 'job': job})


@upload_bp.route('/api/upload/jobs/<job_id>/files', methods=['GET'])
def list_upload_job_files(job_id):
    user, err, status = _require_login()
    if err:
        return err, status
    job = get_upload_job(job_id)
    if not job:
        return jsonify({'error': 'Job 不存在'}), 404
    if job['username'] != user['username'] and user.get('role') != 'admin':
        return jsonify({'error': '无权限'}), 403

    file_status = request.args.get('status')
    limit = min(int(request.args.get('limit', 500)), 1000)
    offset = int(request.args.get('offset', 0))
    files = list_upload_files(job_id, status=file_status, limit=limit, offset=offset)
    total = count_upload_files(job_id, status=file_status)
    return jsonify({'success': True, 'files': files, 'total': total, 'limit': limit, 'offset': offset})


@upload_bp.route('/api/upload/files/<file_id>/start', methods=['POST'])
def start_upload_file(file_id):
    file_record = get_upload_file(file_id)
    if not file_record:
        return jsonify({'error': '文件任务不存在'}), 404
    job, target, ctx, err, status = _job_context(file_record)
    if err:
        return err, status
    credential, config, adapter = ctx

    if file_record['status'] not in {UPLOAD_FILE_PENDING, UPLOAD_FILE_FAILED}:
        return jsonify({'error': f"当前状态不可 start: {file_record['status']}"}), 400

    update_upload_job(job['id'], {'status': UPLOAD_JOB_RUNNING})
    update_upload_file(file_id, {
        'status': UPLOAD_FILE_UPLOADING,
        'started_at': datetime.now().isoformat(),
        'error': None,
    })

    object_key = file_record['storage_key']
    mime = file_record.get('mime')
    file_size = file_record['size']

    origin = request.headers.get('Origin')
    cors_origins = [origin] if origin else ['*']
    try:
        ensure_browser_cors(adapter, credential, config, cors_origins)
    except Exception as exc:
        logger.warning('自动配置存储 CORS 失败（请手动在控制台配置）: %s', exc)

    if uses_multipart(file_size):
        upload_id, parts, total_parts = adapter.init_multipart(
            credential, config, object_key, file_size, mime=mime,
        )
        part_rows = []
        for part_number in range(1, total_parts + 1):
            part_rows.append({
                'file_id': file_id,
                'part_number': part_number,
                'size': part_size_for(file_size, part_number, total_parts),
                'etag': None,
                'status': 'pending',
            })
        insert_upload_parts(part_rows)
        update_upload_file(file_id, {'upload_id': upload_id})
        return jsonify({
            'success': True,
            'mode': 'multipart',
            'upload_id': upload_id,
            'part_size': UPLOAD_PART_SIZE,
            'total_parts': total_parts,
            'parts': parts,
        })

    upload_url = adapter.presign_put(credential, config, object_key, mime=mime)
    return jsonify({
        'success': True,
        'mode': 'put',
        'upload_url': upload_url,
        'method': 'PUT',
        'headers': {},
    })


@upload_bp.route('/api/upload/files/<file_id>/presign-parts', methods=['POST'])
def presign_upload_parts(file_id):
    file_record = get_upload_file(file_id)
    if not file_record:
        return jsonify({'error': '文件任务不存在'}), 404
    _job, _target, ctx, err, status = _job_context(file_record)
    if err:
        return err, status
    credential, config, adapter = ctx

    data = request.get_json(silent=True) or {}
    start_part = int(data.get('start_part') or 1)
    end_part = int(data.get('end_part') or start_part)
    upload_id = file_record.get('upload_id')
    if not upload_id:
        return jsonify({'error': '尚未初始化 multipart'}), 400

    file_size = file_record['size']
    total_parts = total_parts_for(file_size)
    end_part = min(end_part, total_parts)
    part_rows = []
    for part_number in range(start_part, end_part + 1):
        part_rows.append({
            'file_id': file_id,
            'part_number': part_number,
            'size': part_size_for(file_size, part_number, total_parts),
            'etag': None,
            'status': 'pending',
        })
    insert_upload_parts(part_rows)

    parts = adapter.presign_parts(
        credential, config, file_record['storage_key'], upload_id, start_part, end_part,
    )
    return jsonify({'success': True, 'parts': parts})


@upload_bp.route('/api/upload/files/<file_id>/part-done', methods=['POST'])
def upload_part_done(file_id):
    file_record = get_upload_file(file_id)
    if not file_record:
        return jsonify({'error': '文件任务不存在'}), 404
    _job, _target, _ctx, err, status = _job_context(file_record)
    if err:
        return err, status

    data = request.get_json(silent=True) or {}
    part_number = int(data.get('part_number') or 0)
    etag = (data.get('etag') or '').strip().strip('"')
    if not part_number or not etag:
        return jsonify({'error': 'part_number 与 etag 必填'}), 400

    update_upload_part(file_id, part_number, {'etag': etag, 'status': 'completed'})
    completed_parts = [p for p in list_upload_parts(file_id) if p.get('status') == 'completed']
    bytes_uploaded = sum(p.get('size') or 0 for p in completed_parts)
    update_upload_file(file_id, {
        'bytes_uploaded': min(bytes_uploaded, file_record['size']),
        'status': UPLOAD_FILE_UPLOADING,
    })
    return jsonify({'success': True, 'bytes_uploaded': bytes_uploaded})


@upload_bp.route('/api/upload/files/<file_id>/complete', methods=['POST'])
def complete_upload_file(file_id):
    file_record = get_upload_file(file_id)
    if not file_record:
        return jsonify({'error': '文件任务不存在'}), 404
    job, target, ctx, err, status = _job_context(file_record)
    if err:
        return err, status
    credential, config, adapter = ctx

    update_upload_file(file_id, {'status': UPLOAD_FILE_VERIFYING})
    data = request.get_json(silent=True) or {}
    etag = (data.get('etag') or '').strip().strip('"')

    if file_record.get('upload_id'):
        expected_parts = total_parts_for(file_record['size'])
        parts = [
            {'part_number': p['part_number'], 'etag': p['etag']}
            for p in list_upload_parts(file_id)
            if p.get('status') == 'completed' and p.get('etag')
        ]
        if len(parts) < expected_parts and hasattr(adapter, 'list_uploaded_parts'):
            try:
                remote_parts = adapter.list_uploaded_parts(
                    credential, config, file_record['storage_key'], file_record['upload_id'],
                )
                if len(remote_parts) >= expected_parts:
                    for remote_part in remote_parts:
                        update_upload_part(file_id, remote_part['part_number'], {
                            'etag': remote_part['etag'],
                            'status': 'completed',
                        })
                    parts = remote_parts[:expected_parts]
            except Exception as exc:
                logger.warning('从存储拉取分片列表失败: %s', exc)

        if len(parts) < expected_parts:
            update_upload_file(file_id, {
                'status': UPLOAD_FILE_FAILED,
                'error': f'分片未完成: {len(parts)}/{expected_parts}',
                'finished_at': datetime.now().isoformat(),
            })
            recalculate_upload_job_stats(job['id'])
            _maybe_cleanup_job(job['id'])
            return jsonify({
                'success': False,
                'error': f'分片未完成 ({len(parts)}/{expected_parts})',
            }), 400
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
            recalculate_upload_job_stats(job['id'])
            _maybe_cleanup_job(job['id'])
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
        recalculate_upload_job_stats(job['id'])
        _maybe_cleanup_job(job['id'])
        return jsonify({'success': False, 'error': verify.get('error')}), 400

    refresh_result = None
    public_url = build_public_url(config, file_record['storage_key'])
    if job.get('refresh_after') and target.get('cdn_domain') and public_url:
        refresh_result = _refresh_uploaded_url(target.get('cdn_domain'), public_url)

    update_upload_file(file_id, {
        'status': UPLOAD_FILE_COMPLETED,
        'bytes_uploaded': file_record['size'],
        'etag': verify.get('etag') or etag,
        'error': None,
        'finished_at': datetime.now().isoformat(),
    })
    recalculate_upload_job_stats(job['id'])
    _maybe_cleanup_job(job['id'])

    return jsonify({
        'success': True,
        'etag': verify.get('etag') or etag,
        'public_url': public_url,
        'refresh': refresh_result,
    })


@upload_bp.route('/api/upload/jobs/<job_id>/cleanup', methods=['POST'])
def cleanup_upload_job_route(job_id):
    user, err, status = _require_login()
    if err:
        return err, status
    job = get_upload_job(job_id)
    if not job:
        return jsonify({'success': True, 'message': 'Job 已不存在'})
    if job['username'] != user['username'] and user.get('role') != 'admin':
        return jsonify({'error': '无权限'}), 403
    data = request.get_json(silent=True) or {}
    if data.get('force', True):
        delete_upload_job_cascade(job_id)
        return jsonify({'success': True, 'cleaned': True})
    cleaned = cleanup_finished_upload_job(job_id)
    return jsonify({'success': True, 'cleaned': cleaned})


@upload_bp.route('/api/upload/files/<file_id>/progress', methods=['PATCH'])
def update_upload_progress(file_id):
    file_record = get_upload_file(file_id)
    if not file_record:
        return jsonify({'error': '文件任务不存在'}), 404
    _job, _target, _ctx, err, status = _job_context(file_record)
    if err:
        return err, status

    data = request.get_json(silent=True) or {}
    bytes_uploaded = int(data.get('bytes_uploaded') or 0)
    file_status = data.get('status') or UPLOAD_FILE_UPLOADING
    update_upload_file(file_id, {
        'bytes_uploaded': min(max(bytes_uploaded, 0), file_record['size']),
        'status': file_status,
    })
    return jsonify({'success': True})


@upload_bp.route('/api/upload/files/<file_id>/retry', methods=['POST'])
def retry_upload_file(file_id):
    file_record = get_upload_file(file_id)
    if not file_record:
        return jsonify({'error': '文件任务不存在'}), 404
    _job, _target, _ctx, err, status = _job_context(file_record)
    if err:
        return err, status
    if file_record['status'] != UPLOAD_FILE_FAILED:
        return jsonify({'error': '仅 failed 状态可重试'}), 400

    update_upload_file(file_id, {
        'status': UPLOAD_FILE_PENDING,
        'bytes_uploaded': 0,
        'upload_id': None,
        'etag': None,
        'error': None,
        'retry_count': (file_record.get('retry_count') or 0) + 1,
        'started_at': None,
        'finished_at': None,
    })
    return jsonify({'success': True})
