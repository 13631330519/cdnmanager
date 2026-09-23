import csv
import io
import json
import time
import uuid
from datetime import datetime

import logging

from flask import Blueprint, Response, jsonify, request, stream_with_context

from cdnmanager.common import (
    UPLOAD_BATCH_INIT_SIZE,
    UPLOAD_FILE_COMPLETED,
    UPLOAD_FILE_FAILED,
    UPLOAD_FILE_PENDING,
    UPLOAD_FILE_UPLOADING,
    UPLOAD_FILE_VERIFYING,
    UPLOAD_JOB_MAX_FILES,
    UPLOAD_JOB_RUNNING,
    UPLOAD_PART_SIZE,
    UPLOAD_PRESIGN_BATCH_MAX,
)
from cdnmanager.routes.common import get_session_user, require_login
import cdnmanager.db as db

from cdnmanager.providers.storage.storage_service import (
    ensure_browser_cors,
    get_adapter,
    part_size_for,
    total_parts_for,
    uses_multipart,
)
from cdnmanager.services.storage_refresh_service import refresh_file_for_target
from cdnmanager.services.upload_service import (
    append_manifest_batch,
    batch_refresh_cdn,
    create_upload_job_shell,
    presign_put_batch,
    verify_multipart_parts,
)

logger = logging.getLogger(__name__)

upload_bp = Blueprint('upload_bp', __name__)


def _maybe_cleanup_job(job_id):
    try:
        db.cleanup_finished_upload_job(job_id)
    except Exception as exc:
        logger.warning('清理上传 Job 失败 %s: %s', job_id, exc)


def _require_login():
    login_error = require_login()
    if login_error is not None:
        return None, login_error[0], login_error[1]
    user = get_session_user()
    if not user:
        return None, jsonify({'error': '用户不存在'}), 404
    return user, None, None


def _check_job_access(job, user):
    if job['username'] != user['username'] and user.get('role') != 'admin':
        return jsonify({'error': '无权限'}), 403
    return None


def _job_context(file_record):
    job = db.get_upload_job(file_record['job_id'])
    if not job:
        return None, None, None, jsonify({'error': 'Job 不存在'}), 404
    user, err, status = _require_login()
    if err:
        return None, None, None, err, status
    access_err = _check_job_access(job, user)
    if access_err:
        return None, None, None, access_err, 403
    target = db.get_storage_target(job['storage_target_id'])
    if not target:
        return None, None, None, jsonify({'error': '存储目标不存在'}), 404
    credential = db.get_storage_credential(target['provider'], target['credential_id'])
    if not credential:
        return None, None, None, jsonify({'error': '存储凭据不存在'}), 400
    config = target.get('target_config') or {}
    adapter = get_adapter(target['provider'])
    return job, target, (credential, config, adapter), None, None


def _touch_heartbeat(file_id, extra=None):
    updates = {'last_heartbeat_at': datetime.now().isoformat()}
    if extra:
        updates.update(extra)
    db.update_upload_file(file_id, updates)


def _refresh_uploaded_file(target, storage_key):
    if not target or not storage_key:
        return None
    return refresh_file_for_target(target, storage_key)


@upload_bp.route('/api/upload/jobs', methods=['GET'])
def list_upload_jobs_route():
    user, err, status = _require_login()
    if err:
        return err, status
    limit = min(int(request.args.get('limit', 30)), 100)
    offset = int(request.args.get('offset', 0))
    username = None if user.get('role') == 'admin' and request.args.get('all') == '1' else user['username']
    jobs = db.list_upload_jobs(username=username, limit=limit, offset=offset)
    total = db.count_upload_jobs(username=username)
    return jsonify({'success': True, 'jobs': jobs, 'total': total, 'limit': limit, 'offset': offset})


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

    if len(files) > UPLOAD_BATCH_INIT_SIZE:
        return jsonify({'error': f'首批最多 {UPLOAD_BATCH_INIT_SIZE} 个，请使用 init-batch 追加'}), 400
    if files and len(files) > UPLOAD_JOB_MAX_FILES:
        return jsonify({'error': f'Job 最多 {UPLOAD_JOB_MAX_FILES} 个文件'}), 400

    try:
        job_id, rows, _target = create_upload_job_shell(
            user, storage_target_id, remote_prefix, refresh_after, first_batch=files,
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    return jsonify({
        'success': True,
        'job_id': job_id,
        'files': [{'id': row['id'], 'relative_path': row['relative_path'], 'size': row['size']} for row in rows],
        'batch_size': UPLOAD_BATCH_INIT_SIZE,
        'max_files': UPLOAD_JOB_MAX_FILES,
    })


@upload_bp.route('/api/upload/jobs/<job_id>/init-batch', methods=['POST'])
def init_upload_batch(job_id):
    user, err, status = _require_login()
    if err:
        return err, status
    job = db.get_upload_job(job_id)
    if not job:
        return jsonify({'error': 'Job 不存在'}), 404
    access_err = _check_job_access(job, user)
    if access_err:
        return access_err

    data = request.get_json(silent=True) or {}
    files = data.get('files') or []
    if not files:
        return jsonify({'error': 'files 不能为空'}), 400

    try:
        rows = append_manifest_batch(job_id, files)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    job = db.get_upload_job(job_id)
    return jsonify({
        'success': True,
        'job_id': job_id,
        'added': len(rows),
        'total_files': job['total_files'],
        'files': [{'id': row['id'], 'relative_path': row['relative_path'], 'size': row['size']} for row in rows],
    })


@upload_bp.route('/api/upload/files/presign-batch', methods=['POST'])
def presign_batch_route():
    user, err, status = _require_login()
    if err:
        return err, status

    data = request.get_json(silent=True) or {}
    file_ids = data.get('file_ids') or []
    if not file_ids:
        return jsonify({'error': 'file_ids 必填'}), 400
    if len(file_ids) > UPLOAD_PRESIGN_BATCH_MAX:
        return jsonify({'error': f'单次最多 {UPLOAD_PRESIGN_BATCH_MAX} 个'}), 400

    for file_id in file_ids:
        file_record = db.get_upload_file(file_id)
        if not file_record:
            return jsonify({'error': f'文件不存在: {file_id}'}), 404
        job = db.get_upload_job(file_record['job_id'])
        access_err = _check_job_access(job, user)
        if access_err:
            return access_err

    origin = request.headers.get('Origin')
    started = time.perf_counter()
    results, errors = presign_put_batch(file_ids, origin=origin)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

    return jsonify({
        'success': True,
        'files': results,
        'errors': errors,
        'elapsed_ms': elapsed_ms,
    })


@upload_bp.route('/api/upload/jobs/<job_id>/stream', methods=['GET'])
def upload_job_stream(job_id):
    user, err, status = _require_login()
    if err:
        return err, status
    job = db.get_upload_job(job_id)
    if not job:
        return jsonify({'error': 'Job 不存在'}), 404
    access_err = _check_job_access(job, user)
    if access_err:
        return access_err

    @stream_with_context
    def generate():
        last_payload = None
        for _ in range(3600):
            current = db.get_upload_job(job_id)
            if not current:
                break
            payload = {
                'job_id': job_id,
                'status': current.get('status'),
                'done_files': current.get('done_files'),
                'total_files': current.get('total_files'),
                'done_bytes': current.get('done_bytes'),
                'total_bytes': current.get('total_bytes'),
                'failed_files': current.get('failed_files'),
            }
            encoded = json.dumps(payload, ensure_ascii=False)
            if encoded != last_payload:
                yield f'data: {encoded}\n\n'
                last_payload = encoded
            if current.get('status') in {'completed', 'partial', 'failed', 'cancelled'}:
                break
            time.sleep(1)

    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
    })


@upload_bp.route('/api/upload/jobs/<job_id>/manifest-failures.csv', methods=['GET'])
def export_failures_csv(job_id):
    user, err, status = _require_login()
    if err:
        return err, status
    job = db.get_upload_job(job_id)
    if not job:
        return jsonify({'error': 'Job 不存在'}), 404
    access_err = _check_job_access(job, user)
    if access_err:
        return access_err

    failed = db.list_failed_upload_files(job_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['relative_path', 'size', 'error', 'file_id'])
    for row in failed:
        writer.writerow([row.get('relative_path'), row.get('size'), row.get('error'), row.get('id')])

    return Response(
        output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename=failures-{job_id}.csv'},
    )


@upload_bp.route('/api/upload/jobs/<job_id>/refresh-cdn', methods=['POST'])
def refresh_job_cdn(job_id):
    user, err, status = _require_login()
    if err:
        return err, status
    job = db.get_upload_job(job_id)
    if not job:
        return jsonify({'error': 'Job 不存在'}), 404
    access_err = _check_job_access(job, user)
    if access_err:
        return access_err
    target = db.get_storage_target(job['storage_target_id'])
    if not target:
        return jsonify({'error': '存储目标不存在'}), 404
    result = batch_refresh_cdn(job, target)
    return jsonify({'success': True, **result})


@upload_bp.route('/api/upload/jobs/<job_id>', methods=['GET'])
def get_upload_job_route(job_id):
    user, err, status = _require_login()
    if err:
        return err, status
    job = db.get_upload_job(job_id)
    if not job:
        return jsonify({'error': 'Job 不存在'}), 404
    access_err = _check_job_access(job, user)
    if access_err:
        return access_err
    return jsonify({'success': True, 'job': job})


@upload_bp.route('/api/upload/jobs/<job_id>/files', methods=['GET'])
def list_upload_job_files(job_id):
    user, err, status = _require_login()
    if err:
        return err, status
    job = db.get_upload_job(job_id)
    if not job:
        return jsonify({'error': 'Job 不存在'}), 404
    access_err = _check_job_access(job, user)
    if access_err:
        return access_err

    file_status = request.args.get('status')
    limit = min(int(request.args.get('limit', 500)), 1000)
    offset = int(request.args.get('offset', 0))
    files = db.list_upload_files(job_id, status=file_status, limit=limit, offset=offset)
    total = db.count_upload_files(job_id, status=file_status)
    return jsonify({'success': True, 'files': files, 'total': total, 'limit': limit, 'offset': offset})


@upload_bp.route('/api/upload/files/<file_id>/start', methods=['POST'])
def start_upload_file(file_id):
    file_record = db.get_upload_file(file_id)
    if not file_record:
        return jsonify({'error': '文件任务不存在'}), 404
    job, target, ctx, err, status = _job_context(file_record)
    if err:
        return err, status
    credential, config, adapter = ctx

    if file_record['status'] not in {UPLOAD_FILE_PENDING, UPLOAD_FILE_FAILED}:
        return jsonify({'error': f"当前状态不可 start: {file_record['status']}"}), 400

    now = datetime.now().isoformat()
    db.update_upload_job(job['id'], {'status': UPLOAD_JOB_RUNNING})
    _touch_heartbeat(file_id, {
        'status': UPLOAD_FILE_UPLOADING,
        'started_at': file_record.get('started_at') or now,
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
        logger.warning('自动配置存储 CORS 失败: %s', exc)

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
        db.insert_upload_parts(part_rows)
        db.update_upload_file(file_id, {'upload_id': upload_id})
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
    file_record = db.get_upload_file(file_id)
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
    db.insert_upload_parts(part_rows)

    parts = adapter.presign_parts(
        credential, config, file_record['storage_key'], upload_id, start_part, end_part,
    )
    _touch_heartbeat(file_id)
    return jsonify({'success': True, 'parts': parts})


@upload_bp.route('/api/upload/files/<file_id>/part-done', methods=['POST'])
def upload_part_done(file_id):
    file_record = db.get_upload_file(file_id)
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

    db.update_upload_part(file_id, part_number, {'etag': etag, 'status': 'completed'})
    completed_parts = [p for p in db.list_upload_parts(file_id) if p.get('status') == 'completed']
    bytes_uploaded = sum(p.get('size') or 0 for p in completed_parts)
    _touch_heartbeat(file_id, {
        'bytes_uploaded': min(bytes_uploaded, file_record['size']),
        'status': UPLOAD_FILE_UPLOADING,
    })
    return jsonify({'success': True, 'bytes_uploaded': bytes_uploaded})


@upload_bp.route('/api/upload/files/<file_id>/complete', methods=['POST'])
def complete_upload_file(file_id):
    file_record = db.get_upload_file(file_id)
    if not file_record:
        return jsonify({'error': '文件任务不存在'}), 404
    job, target, ctx, err, status = _job_context(file_record)
    if err:
        return err, status
    credential, config, adapter = ctx

    _touch_heartbeat(file_id, {'status': UPLOAD_FILE_VERIFYING})
    data = request.get_json(silent=True) or {}
    etag = (data.get('etag') or '').strip().strip('"')

    if file_record.get('upload_id'):
        expected_parts = total_parts_for(file_record['size'])
        local_parts = [
            {'part_number': p['part_number'], 'etag': p['etag']}
            for p in db.list_upload_parts(file_id)
            if p.get('status') == 'completed' and p.get('etag')
        ]
        parts, verify_err = verify_multipart_parts(
            adapter, credential, config, file_record, local_parts,
        )
        if verify_err:
            if hasattr(adapter, 'list_uploaded_parts'):
                try:
                    remote_parts = adapter.list_uploaded_parts(
                        credential, config, file_record['storage_key'], file_record['upload_id'],
                    )
                    if len(remote_parts) >= expected_parts:
                        for remote_part in remote_parts:
                            db.update_upload_part(file_id, remote_part['part_number'], {
                                'etag': remote_part['etag'],
                                'status': 'completed',
                            })
                        parts, verify_err = verify_multipart_parts(
                            adapter, credential, config, file_record, remote_parts,
                        )
                except Exception as exc:
                    logger.warning('从存储拉取分片列表失败: %s', exc)

        if verify_err or not parts:
            db.update_upload_file(file_id, {
                'status': UPLOAD_FILE_FAILED,
                'error': verify_err or f'分片未完成: {len(local_parts)}/{expected_parts}',
                'finished_at': datetime.now().isoformat(),
            })
            db.recalculate_upload_job_stats(job['id'])
            _maybe_cleanup_job(job['id'])
            return jsonify({'success': False, 'error': verify_err or '分片校验失败'}), 400
        try:
            etag = adapter.complete_multipart(
                credential, config, file_record['storage_key'], file_record['upload_id'], parts,
            ) or etag
        except Exception as exc:
            db.update_upload_file(file_id, {
                'status': UPLOAD_FILE_FAILED,
                'error': str(exc),
                'finished_at': datetime.now().isoformat(),
            })
            db.recalculate_upload_job_stats(job['id'])
            _maybe_cleanup_job(job['id'])
            return jsonify({'success': False, 'error': str(exc)}), 400

    verify = adapter.verify_object(
        credential, config, file_record['storage_key'], file_record['size'],
    )
    if not verify.get('ok'):
        db.update_upload_file(file_id, {
            'status': UPLOAD_FILE_FAILED,
            'error': verify.get('error') or '校验失败',
            'finished_at': datetime.now().isoformat(),
        })
        db.recalculate_upload_job_stats(job['id'])
        _maybe_cleanup_job(job['id'])
        return jsonify({'success': False, 'error': verify.get('error')}), 400

    refresh_result = None
    public_url = None
    if job.get('refresh_after'):
        refresh_result = _refresh_uploaded_file(target, file_record['storage_key'])
        if refresh_result and refresh_result.get('results'):
            first = refresh_result['results'][0]
            public_url = first.get('url')

    db.update_upload_file(file_id, {
        'status': UPLOAD_FILE_COMPLETED,
        'bytes_uploaded': file_record['size'],
        'etag': verify.get('etag') or etag,
        'error': None,
        'finished_at': datetime.now().isoformat(),
        'last_heartbeat_at': datetime.now().isoformat(),
    })
    db.recalculate_upload_job_stats(job['id'])
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
    job = db.get_upload_job(job_id)
    if not job:
        return jsonify({'success': True, 'message': 'Job 已不存在'})
    access_err = _check_job_access(job, user)
    if access_err:
        return access_err
    data = request.get_json(silent=True) or {}
    if data.get('force', False):
        db.delete_upload_job_cascade(job_id)
        return jsonify({'success': True, 'cleaned': True})
    cleaned = db.cleanup_finished_upload_job(job_id)
    return jsonify({'success': True, 'cleaned': cleaned})


@upload_bp.route('/api/upload/files/<file_id>/progress', methods=['PATCH'])
def update_upload_progress(file_id):
    file_record = db.get_upload_file(file_id)
    if not file_record:
        return jsonify({'error': '文件任务不存在'}), 404
    _job, _target, _ctx, err, status = _job_context(file_record)
    if err:
        return err, status

    data = request.get_json(silent=True) or {}
    bytes_uploaded = int(data.get('bytes_uploaded') or 0)
    file_status = data.get('status') or UPLOAD_FILE_UPLOADING
    _touch_heartbeat(file_id, {
        'bytes_uploaded': min(max(bytes_uploaded, 0), file_record['size']),
        'status': file_status,
    })
    return jsonify({'success': True})


@upload_bp.route('/api/upload/files/<file_id>/retry', methods=['POST'])
def retry_upload_file(file_id):
    file_record = db.get_upload_file(file_id)
    if not file_record:
        return jsonify({'error': '文件任务不存在'}), 404
    _job, _target, _ctx, err, status = _job_context(file_record)
    if err:
        return err, status
    if file_record['status'] != UPLOAD_FILE_FAILED:
        return jsonify({'error': '仅 failed 状态可重试'}), 400

    db.update_upload_file(file_id, {
        'status': UPLOAD_FILE_PENDING,
        'bytes_uploaded': 0,
        'upload_id': None,
        'etag': None,
        'error': None,
        'retry_count': (file_record.get('retry_count') or 0) + 1,
        'started_at': None,
        'finished_at': None,
        'last_heartbeat_at': None,
    })
    return jsonify({'success': True})
