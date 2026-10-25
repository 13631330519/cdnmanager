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
    UPLOAD_FILE_VERIFYING,
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
    """Presign small-file PUT URLs.

    Job, target, credential, and adapter are loaded once per job. Browser CORS
    is ensured once per storage target in the batch, not once per file.
    """
    if len(file_ids) > UPLOAD_PRESIGN_BATCH_MAX:
        raise ValueError(f'单次 presign 最多 {UPLOAD_PRESIGN_BATCH_MAX} 个文件')

    records = {row['id']: row for row in db.get_upload_files_by_ids(file_ids)}
    job_ids = {row['job_id'] for row in records.values()}
    jobs = {row['id']: row for row in db.get_upload_jobs_by_ids(job_ids)}
    ctx_by_job = {}
    cors_ready = set()
    running_jobs = set()
    cors_origins = [origin] if origin else ['*']

    results = []
    errors = []
    for file_id in file_ids:
        file_record = records.get(file_id)
        if not file_record:
            errors.append({'file_id': file_id, 'error': '文件不存在'})
            continue
        if file_record['status'] not in {UPLOAD_FILE_PENDING, UPLOAD_FILE_FAILED}:
            errors.append({'file_id': file_id, 'error': f"状态不可 presign: {file_record['status']}"})
            continue
        if storage_service.uses_multipart(file_record['size']):
            errors.append({'file_id': file_id, 'error': '大文件请使用 start/multipart'})
            continue

        job = jobs.get(file_record['job_id'])
        if not job:
            errors.append({'file_id': file_id, 'error': 'Job 不存在'})
            continue
        if job['id'] not in ctx_by_job:
            try:
                ctx_by_job[job['id']] = _job_storage_ctx(job)
            except ValueError as exc:
                ctx_by_job[job['id']] = exc
        ctx = ctx_by_job[job['id']]
        if isinstance(ctx, Exception):
            errors.append({'file_id': file_id, 'error': str(ctx)})
            continue
        target, credential, config, adapter = ctx

        target_id = target.get('id') or job['storage_target_id']
        if target_id not in cors_ready:
            cors_ready.add(target_id)
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
        if job['id'] not in running_jobs:
            db.update_upload_job(job['id'], {'status': UPLOAD_JOB_RUNNING})
            running_jobs.add(job['id'])
        results.append({
            'file_id': file_id,
            'mode': 'put',
            'upload_url': upload_url,
            'method': 'PUT',
        })
    return results, errors


def _complete_result(success, etag=None, error=None, status_code=200, refresh=None):
    return {
        'success': success,
        'etag': etag,
        'error': error,
        'status_code': status_code,
        'refresh': refresh,
    }


def _fail_completed_file(job_id, file_id, error):
    db.update_upload_file(file_id, {
        'status': UPLOAD_FILE_FAILED,
        'error': error,
        'finished_at': datetime.now().isoformat(),
    })
    db.recalculate_upload_job_stats(job_id)
    finalize_finished_job(job_id)
    return _complete_result(False, error=error, status_code=400)


def complete_upload_file(job, file_record, *, etag=None, proxy=False):
    """Validate one finished file and mark it completed.

    FTP/SFTP/FTPS proxy tolerance — browser ``proxy: true`` and the external
    complete call after ``/api/upload/proxy`` use the same rule:

    When ``proxy`` is true and the target is FTP-family, ``verify_object`` is
    best-effort. A failed SIZE/stat or a verify exception does not fail the
    file, because the proxy endpoint already stored the bytes. A successful
    verify still records the remote size. Object storage (OSS/COS/OOS) and
    non-proxy completes stay strict: verify failure marks the file failed.

    Routes keep authentication and decide when ``proxy`` is true. The external
    API sets it only after the proxy upload has stored bytes, so a complete
    before that upload still fails verification.
    """
    file_id = file_record['id']
    job_id = job['id']
    etag = (etag or '').strip().strip('"')

    try:
        target, credential, config, adapter = _job_storage_ctx(job)
    except ValueError as exc:
        return _complete_result(False, error=str(exc), status_code=400)

    now = datetime.now().isoformat()
    db.update_upload_file(file_id, {
        'status': UPLOAD_FILE_VERIFYING,
        'last_heartbeat_at': now,
    })

    ftp_family = storage_service.is_ftp_family(target.get('provider'))
    tolerate_proxy_verify = bool(proxy) and ftp_family

    if file_record.get('upload_id') and not tolerate_proxy_verify:
        expected_parts = storage_service.total_parts_for(file_record['size'])
        local_parts = [
            {'part_number': part['part_number'], 'etag': part['etag']}
            for part in db.list_upload_parts(file_id)
            if part.get('status') == 'completed' and part.get('etag')
        ]
        parts, verify_err = verify_multipart_parts(
            adapter, credential, config, file_record, local_parts,
        )
        if verify_err and hasattr(adapter, 'list_uploaded_parts'):
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
            message = verify_err or f'分片未完成: {len(local_parts)}/{expected_parts}'
            return _fail_completed_file(job_id, file_id, message)
        try:
            etag = adapter.complete_multipart(
                credential, config, file_record['storage_key'], file_record['upload_id'], parts,
            ) or etag
        except Exception as exc:
            return _fail_completed_file(job_id, file_id, str(exc))

    if tolerate_proxy_verify:
        verify = {'ok': True, 'size': file_record['size'], 'etag': None}
        try:
            checked = adapter.verify_object(
                credential, config, file_record['storage_key'], file_record['size'],
            )
            if checked.get('ok'):
                verify = checked
            else:
                logger.warning(
                    'FTP 代理上传后校验未通过，仍按上传成功处理: %s',
                    checked.get('error') or '校验失败',
                )
        except Exception as exc:
            logger.warning('FTP 代理上传后校验失败，仍按上传成功处理: %s', exc)
    else:
        verify = adapter.verify_object(
            credential, config, file_record['storage_key'], file_record['size'],
        )
        if not verify.get('ok'):
            return _fail_completed_file(job_id, file_id, verify.get('error') or '校验失败')

    finished = datetime.now().isoformat()
    final_etag = verify.get('etag') or etag
    db.update_upload_file(file_id, {
        'status': UPLOAD_FILE_COMPLETED,
        'bytes_uploaded': file_record['size'],
        'etag': final_etag,
        'error': None,
        'finished_at': finished,
        'last_heartbeat_at': finished,
    })
    db.recalculate_upload_job_stats(job_id)
    refresh_result = finalize_finished_job(job_id)
    return _complete_result(True, etag=final_etag, refresh=refresh_result)


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

    # claim_finished_job_cdn_refresh counts active files once inside the write
    # transaction, so finalize does not repeat count_upload_files.
    if not db.claim_finished_job_cdn_refresh(job_id):
        return None
    target = db.get_storage_target(job['storage_target_id'])
    try:
        refresh_result = refresh_completed_job_files(job, target)
    except Exception:
        refresh_result = {'success': False, 'error': 'CDN 刷新失败', 'file_count': 0}
    db.cleanup_finished_upload_job(job_id)
    return refresh_result
