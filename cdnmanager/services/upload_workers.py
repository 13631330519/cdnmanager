"""Background workers for upload job maintenance."""

import logging
import threading
import time
from datetime import datetime, timedelta

from cdnmanager.common import UPLOAD_FILE_FAILED, UPLOAD_HEARTBEAT_TIMEOUT
from cdnmanager.config import ENABLE_UPLOAD_TIMEOUT_SCAN
import cdnmanager.db as db
import cdnmanager.services.upload_service as upload_service


logger = logging.getLogger(__name__)


def scan_upload_timeouts_once():
    cutoff = (datetime.now() - timedelta(seconds=UPLOAD_HEARTBEAT_TIMEOUT)).isoformat()
    stale_files = db.list_stale_uploading_files(cutoff)
    if not stale_files:
        return 0

    job_ids = set()
    for file_record in stale_files:
        db.update_upload_file(file_record['id'], {
            'status': UPLOAD_FILE_FAILED,
            'error': '上传心跳超时（>15 分钟无进度）',
            'finished_at': datetime.now().isoformat(),
        })
        job_ids.add(file_record['job_id'])

    for job_id in job_ids:
        db.recalculate_upload_job_stats(job_id)

    logger.info('上传超时扫描: 标记 %s 个文件失败', len(stale_files))
    return len(stale_files)


def reclaim_open_manifest_jobs_once():
    """Close abandoned open manifests after disconnect / timeout, then finalize."""
    cutoff = (datetime.now() - timedelta(seconds=UPLOAD_HEARTBEAT_TIMEOUT)).isoformat()
    jobs = db.list_open_manifest_jobs()
    if not jobs:
        return 0

    reclaimed = 0
    for job in jobs:
        job_id = job['id']
        active = db.count_active_upload_files(job_id)

        if active == 0:
            upload_service.close_upload_manifest(job_id)
            reclaimed += 1
            continue

        created_at = job.get('created_at') or ''
        if created_at > cutoff:
            continue
        if db.job_has_recent_upload_activity(job_id, cutoff):
            continue

        db.fail_active_upload_files(job_id, '上传中断（客户端断开或超时）')
        db.recalculate_upload_job_stats(job_id)
        upload_service.close_upload_manifest(job_id)
        reclaimed += 1

    if reclaimed:
        logger.info('上传清单收口: 关闭 %s 个未关闭 manifest 的 Job', reclaimed)
    return reclaimed


def start_upload_timeout_thread():
    if not ENABLE_UPLOAD_TIMEOUT_SCAN:
        return

    def worker():
        # One lease per interval so multi-worker gunicorn does not scan the same
        # stale uploads twice. The holder refreshes the 90s lease; others skip.
        while True:
            try:
                if db.try_acquire_upload_timeout_lease():
                    scan_upload_timeouts_once()
                    reclaim_open_manifest_jobs_once()
            except Exception as exc:
                logger.warning('上传超时扫描异常: %s', exc)
            time.sleep(60)

    thread = threading.Thread(target=worker, daemon=True, name='upload-timeout-scanner')
    thread.start()
