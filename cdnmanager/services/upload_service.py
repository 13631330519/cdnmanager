"""Upload orchestration — manifest batching, presign batch, verify, CDN refresh."""

import uuid
from datetime import datetime

from cdnmanager.common import (
    UPLOAD_BATCH_INIT_SIZE,
    UPLOAD_FILE_COMPLETED,
    UPLOAD_FILE_FAILED,
    UPLOAD_FILE_PENDING,
    UPLOAD_FILE_UPLOADING,
    UPLOAD_JOB_MAX_FILES,
    UPLOAD_JOB_PENDING,
    UPLOAD_JOB_RUNNING,
    UPLOAD_PRESIGN_BATCH_MAX,
)
from cdnmanager.db.models import (
    get_storage_credential,
    get_storage_target,
    get_upload_file,
    get_upload_job,
    increment_upload_job_totals,
    insert_upload_files,
    insert_upload_job,
    list_upload_files,
    update_upload_job,
)
from cdnmanager.providers.storage_service import (
    build_object_key,
    build_public_url,
    get_adapter,
    total_parts_for,
    uses_multipart,
)
from cdnmanager.routes.cdn.credentials import get_credential
from cdnmanager.routes.cdn.domains import find_bound_domain
from cdnmanager.services.refresh_service import refresh_and_record


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
            'storage_key': build_object_key(config, remote_prefix, relative_path),
            'upload_id': None,
            'etag': None,
            'error': None,
            'retry_count': 0,
            'started_at': None,
            'finished_at': None,
            'last_heartbeat_at': None,
        })
    return rows, total_bytes


def create_upload_job_shell(user, storage_target_id, remote_prefix, refresh_after, first_batch=None):
    target = get_storage_target(storage_target_id)
    if not target:
        raise ValueError('存储目标不存在')

    first_batch = first_batch or []
    if len(first_batch) > UPLOAD_BATCH_INIT_SIZE:
        raise ValueError(f'单批最多 {UPLOAD_BATCH_INIT_SIZE} 个文件')

    job_id = uuid.uuid4().hex[:16]
    rows, total_bytes = build_file_rows(target, job_id, remote_prefix, first_batch) if first_batch else ([], 0)

    insert_upload_job({
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
        'refresh_after': refresh_after,
        'created_at': datetime.now().isoformat(),
        'finished_at': None,
    })
    if rows:
        insert_upload_files(rows)
    return job_id, rows, target


def append_manifest_batch(job_id, files):
    job = get_upload_job(job_id)
    if not job:
        raise ValueError('Job 不存在')
    if job['status'] not in {UPLOAD_JOB_PENDING, UPLOAD_JOB_RUNNING}:
        raise ValueError(f'Job 状态不可追加: {job["status"]}')

    if len(files) > UPLOAD_BATCH_INIT_SIZE:
        raise ValueError(f'单批最多 {UPLOAD_BATCH_INIT_SIZE} 个文件')
    if job['total_files'] + len(files) > UPLOAD_JOB_MAX_FILES:
        raise ValueError(f'Job 总文件数不能超过 {UPLOAD_JOB_MAX_FILES}')

    target = get_storage_target(job['storage_target_id'])
    if not target:
        raise ValueError('存储目标不存在')

    rows, total_bytes = build_file_rows(target, job_id, job.get('remote_prefix') or '', files)
    insert_upload_files(rows)
    increment_upload_job_totals(job_id, len(rows), total_bytes)
    if job['status'] == UPLOAD_JOB_PENDING:
        update_upload_job(job_id, {'status': UPLOAD_JOB_PENDING})
    return rows


def _job_storage_ctx(job):
    target = get_storage_target(job['storage_target_id'])
    if not target:
        raise ValueError('存储目标不存在')
    credential = get_storage_credential(target['provider'], target['credential_id'])
    if not credential:
        raise ValueError('存储凭据不存在')
    config = target.get('target_config') or {}
    adapter = get_adapter(target['provider'])
    return target, credential, config, adapter


def presign_put_batch(file_ids, origin=None):
    if len(file_ids) > UPLOAD_PRESIGN_BATCH_MAX:
        raise ValueError(f'单次 presign 最多 {UPLOAD_PRESIGN_BATCH_MAX} 个文件')

    results = []
    errors = []
    for file_id in file_ids:
        file_record = get_upload_file(file_id)
        if not file_record:
            errors.append({'file_id': file_id, 'error': '文件不存在'})
            continue
        if file_record['status'] not in {UPLOAD_FILE_PENDING, UPLOAD_FILE_FAILED}:
            errors.append({'file_id': file_id, 'error': f"状态不可 presign: {file_record['status']}"})
            continue
        if uses_multipart(file_record['size']):
            errors.append({'file_id': file_id, 'error': '大文件请使用 start/multipart'})
            continue

        job = get_upload_job(file_record['job_id'])
        try:
            target, credential, config, adapter = _job_storage_ctx(job)
        except ValueError as exc:
            errors.append({'file_id': file_id, 'error': str(exc)})
            continue

        from cdnmanager.providers.storage_service import ensure_browser_cors
        cors_origins = [origin] if origin else ['*']
        try:
            ensure_browser_cors(adapter, credential, config, cors_origins)
        except Exception:
            pass

        try:
            upload_url = adapter.presign_put(
                credential, config, file_record['storage_key'], mime=file_record.get('mime'),
            )
        except Exception as exc:
            errors.append({'file_id': file_id, 'error': str(exc)})
            continue
        now = datetime.now().isoformat()
        from cdnmanager.db.models import update_upload_file
        update_upload_file(file_id, {
            'status': UPLOAD_FILE_UPLOADING,
            'started_at': file_record.get('started_at') or now,
            'last_heartbeat_at': now,
            'error': None,
        })
        update_upload_job(job['id'], {'status': UPLOAD_JOB_RUNNING})
        results.append({
            'file_id': file_id,
            'mode': 'put',
            'upload_url': upload_url,
            'method': 'PUT',
        })
    return results, errors


def verify_multipart_parts(adapter, credential, config, file_record, local_parts):
    expected = total_parts_for(file_record['size'])
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


def batch_refresh_cdn(job, target, limit=200):
    if not job.get('refresh_after') or not target.get('cdn_domain'):
        return {'success': True, 'refreshed': 0, 'skipped': True}

    config = target.get('target_config') or {}
    cdn_domain = target.get('cdn_domain')
    domain_record = find_bound_domain(cdn_domain)
    if not domain_record:
        return {'success': False, 'error': '未找到绑定的 CDN 域名', 'refreshed': 0}

    credential = get_credential(domain_record.get('provider'), domain_record.get('credential_id'))
    if not credential:
        return {'success': False, 'error': 'CDN 凭据不存在', 'refreshed': 0}

    refreshed = failed = 0
    offset = 0
    while refreshed + failed < limit:
        files = list_upload_files(job['id'], status=UPLOAD_FILE_COMPLETED, limit=100, offset=offset)
        if not files:
            break
        offset += len(files)
        for file_record in files:
            public_url = build_public_url(config, file_record['storage_key'])
            if not public_url:
                continue
            result = refresh_and_record(domain_record, credential, url=public_url, record_url=True)
            if result.get('success'):
                refreshed += 1
            else:
                failed += 1

    return {'success': True, 'refreshed': refreshed, 'failed': failed}
