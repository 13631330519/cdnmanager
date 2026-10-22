"""Upload orchestration — manifest batching, presign batch, verify, CDN refresh."""

import logging
import uuid
from datetime import datetime

from cdnmanager.common import (
    UPLOAD_BATCH_INIT_SIZE,
    UPLOAD_FILE_COMPLETED,
    UPLOAD_FILE_FAILED,
    UPLOAD_FILE_PENDING,
    UPLOAD_FILE_UPLOADING,
    UPLOAD_JOB_COMPLETED,
    UPLOAD_JOB_FAILED,
    UPLOAD_JOB_MAX_FILES,
    UPLOAD_JOB_PARTIAL,
    UPLOAD_JOB_PENDING,
    UPLOAD_JOB_RUNNING,
    UPLOAD_PRESIGN_BATCH_MAX,
)
import cdnmanager.db as db
import cdnmanager.providers.storage.storage_service as storage_service
import cdnmanager.services.storage_refresh_service as storage_refresh_service

logger = logging.getLogger(__name__)


def build_file_rows(target, job_id, remote_prefix, files):
    rows = []
    total_bytes = 0
    config = target.get('target_config') or {}
    for item in files:
        relative_path = (item.get('relative_path') or item.get('path') or '').replace('\\', '/').lstrip('/')
        if not relative_path:
            raise ValueError('files.relative_path 必填')
        size = int(item.get('size') or 0)
        if size < 0:
            raise ValueError('files.size 非法')
        total_bytes += size
        file_id = uuid.uuid4().hex[:16]
        rows.append({
            'id': file_id,
            'job_id': job_id,
            'relative_path': relative_path,
            'size': size,
            'mime': item.get('mime') or 'application/octet-stream',
            'status': UPLOAD_FILE_PENDING,
            'bytes_uploaded': 0,
            'storage_key': storage_service.build_object_key(config, remote_prefix, relative_path),
            'upload_id': None,
            'etag': None,
            'error': None,
            'retry_count': 0,
            'started_at': None,
            'finished_at': None,
            'last_heartbeat_at': None,
        })
    return rows, total_bytes


def create_upload_job_shell(user, storage_target_id, remote_prefix, first_batch=None, keep_open=False):
    target = db.get_storage_target(storage_target_id)
    if not target:
        raise ValueError('存储目标不存在')

    first_batch = first_batch or []
    if len(first_batch) > UPLOAD_BATCH_INIT_SIZE:
        raise ValueError(f'单批最多 {UPLOAD_BATCH_INIT_SIZE} 个文件')

    job_id = uuid.uuid4().hex[:16]
    rows, total_bytes = build_file_rows(target, job_id, remote_prefix, first_batch) if first_batch else ([], 0)

    db.insert_upload_job({
        'id': job_id,
        'username': user['username'],
        'storage_target_id': storage_target_id,
        'remote_prefix': remote_prefix,
        'status': UPLOAD_JOB_PENDING,
        'total_files': len(rows),
        'total_bytes': total_bytes,
        'done_files': 0,
        'done_bytes': 0,
        'failed_files': 0,
        'created_at': datetime.now().isoformat(),
        'finished_at': None,
        'manifest_open': 1 if keep_open else 0,
    })
    if rows:
        db.insert_upload_files(rows)
    return job_id, rows, target


def append_manifest_batch(job_id, files):
    job = db.get_upload_job(job_id)
    if not job:
        raise ValueError('Job 不存在')
    open_manifest = bool(job.get('manifest_open'))
    allowed = {UPLOAD_JOB_PENDING, UPLOAD_JOB_RUNNING}
    if open_manifest:
        allowed.update({UPLOAD_JOB_COMPLETED, UPLOAD_JOB_PARTIAL, UPLOAD_JOB_FAILED})
    if job['status'] not in allowed:
        raise ValueError(f'Job 状态不可追加: {job["status"]}')

    if len(files) > UPLOAD_BATCH_INIT_SIZE:
        raise ValueError(f'单批最多 {UPLOAD_BATCH_INIT_SIZE} 个文件')
    if job['total_files'] + len(files) > UPLOAD_JOB_MAX_FILES:
        raise ValueError(f'Job 总文件数不能超过 {UPLOAD_JOB_MAX_FILES}')

    target = db.get_storage_target(job['storage_target_id'])
    if not target:
        raise ValueError('存储目标不存在')

    rows, total_bytes = build_file_rows(target, job_id, job.get('remote_prefix') or '', files)
    db.insert_upload_files(rows)
    db.increment_upload_job_totals(job_id, len(rows), total_bytes)
    if open_manifest or job['status'] == UPLOAD_JOB_PENDING:
        db.update_upload_job(job_id, {'status': UPLOAD_JOB_RUNNING if open_manifest else UPLOAD_JOB_PENDING})
    return rows


def _job_storage_ctx(job):
    target = db.get_storage_target(job['storage_target_id'])
    if not target:
        raise ValueError('存储目标不存在')
    credential = db.get_storage_credential(target['provider'], target['credential_id'])
    if not credential:
        raise ValueError('存储凭据不存在')
    config = target.get('target_config') or {}
    adapter = storage_service.get_adapter(target['provider'])
    return target, credential, config, adapter


def presign_put_batch(file_ids, origin=None):
    if len(file_ids) > UPLOAD_PRESIGN_BATCH_MAX:
        raise ValueError(f'单次 presign 最多 {UPLOAD_PRESIGN_BATCH_MAX} 个文件')

    results = []
    errors = []
    for file_id in file_ids:
        file_record = db.get_upload_file(file_id)
        if not file_record:
            errors.append({'file_id': file_id, 'error': '文件不存在'})
            continue
        if file_record['status'] not in {UPLOAD_FILE_PENDING, UPLOAD_FILE_FAILED}:
            errors.append({'file_id': file_id, 'error': f"状态不可 presign: {file_record['status']}"})
            continue
        if storage_service.uses_multipart(file_record['size']):
            errors.append({'file_id': file_id, 'error': '大文件请使用 start/multipart'})
            continue

        job = db.get_upload_job(file_record['job_id'])
        try:
            target, credential, config, adapter = _job_storage_ctx(job)
        except ValueError as exc:
            errors.append({'file_id': file_id, 'error': str(exc)})
            continue

        cors_origins = [origin] if origin else ['*']
        try:
            storage_service.ensure_browser_cors(adapter, credential, config, cors_origins)
        except Exception as exc:
            logger.warning('自动配置存储 CORS 失败: %s', exc)

        try:
            upload_url = adapter.presign_put(
                credential, config, file_record['storage_key'], mime=file_record.get('mime'),
            )
        except Exception as exc:
            errors.append({'file_id': file_id, 'error': str(exc)})
            continue
        now = datetime.now().isoformat()
        db.update_upload_file(file_id, {
            'status': UPLOAD_FILE_UPLOADING,
            'started_at': file_record.get('started_at') or now,
            'last_heartbeat_at': now,
            'error': None,
        })
        db.update_upload_job(job['id'], {'status': UPLOAD_JOB_RUNNING})
        results.append({
            'file_id': file_id,
            'mode': 'put',
            'upload_url': upload_url,
            'method': 'PUT',
        })
    return results, errors


def verify_multipart_parts(adapter, credential, config, file_record, local_parts):
    expected = storage_service.total_parts_for(file_record['size'])
    if not hasattr(adapter, 'list_uploaded_parts'):
        return local_parts[:expected], None

    remote_parts = adapter.list_uploaded_parts(
        credential, config, file_record['storage_key'], file_record['upload_id'],
    )
    if len(remote_parts) < expected:
        return None, f'远程分片不足: {len(remote_parts)}/{expected}'

    remote_map = {p['part_number']: p['etag'] for p in remote_parts}
    merged = []
    for part in sorted(local_parts, key=lambda p: p['part_number']):
        pn = part['part_number']
        etag = part.get('etag')
        remote_etag = remote_map.get(pn)
        if remote_etag and etag and remote_etag.replace('"', '') != etag.replace('"', ''):
            return None, f'分片 {pn} ETag 不一致'
        merged.append({'part_number': pn, 'etag': remote_etag or etag})

    for pn in range(1, expected + 1):
        if pn not in remote_map:
            return None, f'缺少分片 {pn}'

    return merged[:expected], None


def refresh_completed_job_files(job, target):
    """Refresh successful uploads by highest directory prefixes, not per file."""
    if not target or not target.get('environment_id'):
        return {'success': False, 'error': '存储目标未绑定项目/环境', 'refreshed': 0, 'file_count': 0}

    keys = []
    offset = 0
    while True:
        files = db.list_upload_files(job['id'], status=UPLOAD_FILE_COMPLETED, limit=500, offset=offset)
        if not files:
            break
        offset += len(files)
        for file_record in files:
            storage_key = file_record.get('storage_key')
            if storage_key:
                keys.append(storage_key)

    if not keys:
        return {'success': True, 'refreshed': 0, 'failed': 0, 'skipped': True, 'file_count': 0}

    # 文件夹上传按最高公共目录刷新（URL 以 / 结尾），避免逐文件/逐子目录提交。
    return storage_refresh_service.refresh_files_for_target(target, keys, collapse_dirs=True)


def close_upload_manifest(job_id):
    """Stop accepting files, then refresh and clean up if every file is finished."""
    job = db.get_upload_job(job_id)
    if not job:
        raise ValueError('Job 不存在')
    if job.get('manifest_open'):
        db.update_upload_job(job_id, {'manifest_open': 0})
    db.recalculate_upload_job_stats(job_id)
    return finalize_finished_job(job_id)


def finalize_finished_job(job_id):
    """When every file is finished, refresh successful files once, then delete the job."""
    try:
        return _finalize_finished_job(job_id)
    except Exception as exc:
        logger.warning('结束上传 Job 失败 %s: %s', job_id, exc)
        return None


def _finalize_finished_job(job_id):
    job = db.get_upload_job(job_id)
    if not job:
        return None
    if job.get('manifest_open'):
        return None
    if job.get('status') not in {'completed', 'partial', 'failed', 'cancelled'}:
        return None

    active = db.count_upload_files(job_id, status='pending')
    active += db.count_upload_files(job_id, status='uploading')
    active += db.count_upload_files(job_id, status='verifying')
    if active:
        return None

    if not db.claim_finished_job_cdn_refresh(job_id):
        return None
    target = db.get_storage_target(job['storage_target_id'])
    try:
        refresh_result = refresh_completed_job_files(job, target)
    except Exception:
        refresh_result = {'success': False, 'error': 'CDN 刷新失败', 'file_count': 0}
    db.cleanup_finished_upload_job(job_id)
    return refresh_result
